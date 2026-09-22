"""Bounded, metadata-only event journal shared by the two services."""

import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from starlette.routing import Match

request_context = ContextVar("meetingbot_audit_context", default=None)
# Payloads, credentials, URLs, SQL, exception messages and user text are never accepted.
FIELDS = {
    "request_id",
    "subject",
    "role",
    "method",
    "route",
    "status",
    "duration_ms",
    "error_type",
    "session_id",
    "job_id",
    "event_id",
    "utterance_id",
    "revision",
    "state",
    "previous_state",
    "mode",
    "operation",
    "table",
    "rows",
    "stage",
    "direction",
    "message_type",
    "bytes",
    "code",
    "count",
    "page",
    "target",
    "action",
    "authenticated",
    "demo",
    "keyless",
    "workspace_id",
    "revision_id",
    "transaction_id",
    "outcome",
    "parent_request_id",
}


class AuditLog:
    def __init__(self, directory, service, max_bytes=10 * 1024 * 1024, backups=5):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "events.jsonl"
        self.service = service
        # Create with private permissions before opening the logging handler.
        fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        self.handler = RotatingFileHandler(
            self.path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"
        )
        self.handler.setFormatter(logging.Formatter("%(message)s"))
        self.handler.rotator = self._rotate

    @staticmethod
    def _rotate(source, destination):
        os.rename(source, destination)
        fd = os.open(source, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)

    def emit(self, event, **fields):
        values = {**(request_context.get() or {}), **fields}
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": self.service,
            "event": event,
            "id": uuid.uuid4().hex,
        }
        row.update(
            {
                key: value[:200] if isinstance(value, str) else value
                for key, value in values.items()
                if key in FIELDS
                and (value is None or isinstance(value, (str, bool, int, float)))
            }
        )
        record = logging.LogRecord(
            "meetingbot.audit",
            logging.INFO,
            "",
            0,
            json.dumps(row, ensure_ascii=False),
            (),
            None,
        )
        self.handler.handle(record)

    def close(self):
        self.handler.close()


class AuditMiddleware:
    """Outermost user middleware: includes auth denials, streams and disconnects."""

    def __init__(self, app, audit, application):
        self.app, self.audit, self.application = app, audit, application

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            return await self.app(scope, receive, send)
        started = time.monotonic()
        rid = uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = rid
        upstream = (
            dict(scope.get("headers", []))
            .get(b"x-request-id", b"")
            .decode("ascii", errors="ignore")
        )
        context = request_context.set(
            {
                "request_id": rid,
                "parent_request_id": upstream
                if re.fullmatch(r"[a-f0-9]{32}", upstream)
                else None,
            }
        )
        route = "unmatched"
        candidates = []
        for included in self.application.routes:
            # New FastAPI versions defer included routes; older versions flatten them.
            contexts = getattr(included, "effective_route_contexts", None)
            candidates.extend(contexts() if contexts else [included])
        for candidate in candidates:
            match, _ = candidate.matches(scope)
            if match in {Match.FULL, Match.PARTIAL}:
                route = (
                    getattr(candidate, "path", None)
                    or getattr(
                        getattr(candidate, "starlette_route", None), "path", None
                    )
                    or "static"
                )
                if match == Match.FULL:
                    break
        status, error_type = (500 if scope["type"] == "http" else None), None
        self.audit.emit(
            scope["type"] + ".started", method=scope.get("method"), route=route
        )

        def actor():
            principal = scope.get("state", {}).get("principal")
            return (
                {"subject": principal.subject, "role": principal.role}
                if principal
                else {}
            )

        async def observed_receive():
            message = await receive()
            if scope["type"] == "websocket":
                self.audit.emit(
                    "websocket.received",
                    **actor(),
                    route=route,
                    message_type=message["type"],
                    code=message.get("code"),
                    bytes=len(message.get("bytes") or b"")
                    + len((message.get("text") or "").encode()),
                )
            return message

        async def observed_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {
                    **message,
                    "headers": [
                        *message.get("headers", []),
                        (b"x-request-id", rid.encode()),
                    ],
                }
            if scope["type"] == "websocket":
                status = message.get("code", status)
                self.audit.emit(
                    "websocket.sent",
                    **actor(),
                    route=route,
                    message_type=message["type"],
                    code=message.get("code"),
                    bytes=len(message.get("bytes") or b"")
                    + len((message.get("text") or "").encode()),
                )
            await send(message)

        try:
            await self.app(scope, observed_receive, observed_send)
        except BaseException as exc:
            error_type = type(exc).__name__
            raise
        finally:
            self.audit.emit(
                scope["type"] + ".completed",
                **actor(),
                method=scope.get("method"),
                route=route,
                status=status,
                error_type=error_type,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            request_context.reset(context)
