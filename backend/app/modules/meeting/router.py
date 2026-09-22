"""Authenticated, bounded loopback bridge; no speech or LLM dependency in this layer."""

import asyncio
import json
import socket
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from urllib.request import Request as URLRequest

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from meetingbot_access import AccessStore
from pydantic import BaseModel, Field

from app.access import require_owner

router = APIRouter(prefix="/api/stt/meeting")
MAX_RESPONSE = 2 * 1024 * 1024


class UtteranceInput(BaseModel):
    utterance_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=4000)
    status: Literal["stable", "final", "corrected"]
    speaker_id: str | None = Field(default=None, max_length=100)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)


class ContextInput(BaseModel):
    text: str = Field(max_length=1500)
    speaker_id: str | None = Field(default=None, max_length=100)


class AnalyzeInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    utterance: UtteranceInput
    context: list[ContextInput] = Field(default_factory=list, max_length=3)
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RagBridge:
    def __init__(self, settings):
        self.settings = settings
        # Never send the administrator credential through environment proxies or redirects.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.gate = asyncio.Lock()
        self._subscription_secret = None

    def request(self, path, body=None, caller_headers=None, *, subscription=False):
        try:
            token_path = self.settings.rag_token_file or self.settings.data_dir / "local-token"
            credential = token_path.expanduser().read_text().strip()
        except OSError:
            raise HTTPException(503, "RAG_CREDENTIAL_UNAVAILABLE") from None
        headers = {"Authorization": "Bearer " + credential} if caller_headers is None else caller_headers
        if subscription:
            # Only server-owned subscription work uses this identity. RAG must resolve its
            # stored grant; accepting an arbitrary owner from a request body is forbidden.
            if self._subscription_secret is None:
                self._subscription_secret = AccessStore(
                    token_path.expanduser(), self.settings.access_db
                ).service_secret("meeting-subscription")
            headers = {
                "Authorization": "Bearer " + credential,
                "X-Meeting-Subscription": "1",
                "X-Meeting-Bridge-Secret": self._subscription_secret,
            }
        request = URLRequest(
            self.settings.rag_base_url + "/api/rag" + path,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode(),
            headers=headers | {"Content-Type": "application/json"},
            method="GET" if body is None else "POST",
        )
        try:
            # The meeting service caps each of its two LLM calls; reads remain on a worker thread.
            with self.opener.open(request, timeout=10 if subscription else (45 if body else 10)) as response:
                raw = response.read(MAX_RESPONSE + 1)
                status = response.status
        except HTTPError as error:
            if 300 <= error.code < 400:
                raise HTTPException(502, "RAG_REDIRECT_DENIED") from None
            raw, status = error.read(MAX_RESPONSE + 1), error.code
        except (TimeoutError, socket.timeout):
            raise HTTPException(504, "RAG_TIMEOUT") from None
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise HTTPException(504, "RAG_TIMEOUT") from None
            raise HTTPException(503, "RAG_UNAVAILABLE") from None
        except OSError:
            raise HTTPException(503, "RAG_UNAVAILABLE") from None
        if len(raw) > MAX_RESPONSE:
            raise HTTPException(502, "RAG_RESPONSE_TOO_LARGE")
        try:
            data = json.loads(raw)
        except (UnicodeError, ValueError):
            raise HTTPException(502, "RAG_INVALID_RESPONSE") from None
        if status >= 400:
            # Preserve machine-readable reasons without returning upstream internals or credentials.
            code = (
                data.get("error_code", "RAG_REQUEST_FAILED")
                if isinstance(data, dict)
                else "RAG_REQUEST_FAILED"
            )
            return JSONResponse({"detail": code}, status_code=status)
        return data


def canonical_payload(service, body):
    session = service.repo.get(body.session_id)
    if not session:
        raise HTTPException(404, "SESSION_NOT_FOUND")
    current = next(
        (u for u in session["utterances"] if u["utterance_id"] == body.utterance.utterance_id), None
    )
    if (
        current is None
        or current["status"] not in {"stable", "corrected"}
        or any(current[key] != getattr(body.utterance, key) for key in ("text", "start_ms", "end_ms"))
    ):
        raise HTTPException(409, "STALE_UTTERANCE")
    utterance = {key: current[key] for key in UtteranceInput.model_fields}
    utterance["status"] = "stable"
    preceding = [
        u
        for u in session["utterances"]
        if u["status"] in {"stable", "corrected"}
        and u["end_ms"] <= current["start_ms"]
        and u["utterance_id"] != current["utterance_id"]
    ]
    context = [
        {"text": u["text"][:1500], "speaker_id": u["speaker_id"]}
        for u in sorted(preceding, key=lambda u: u["end_ms"])[-3:]
    ]
    return {
        "session_id": session["id"],
        "utterance": utterance,
        "context": context,
        "revision_id": body.revision_id,
    }


def caller_headers(request):
    headers = {
        name: request.headers[name]
        for name in ("Authorization", "Cookie", "X-CSRF-Token")
        if request.headers.get(name)
    }
    if request.headers.get("origin"):
        headers["Origin"] = request.app.state.service.settings.rag_base_url
    return headers


@router.get("/config")
async def config(request: Request):
    return {"rag_url": request.app.state.service.settings.rag_public_url}


@router.get("/workspaces")
async def workspaces(request: Request):
    return await asyncio.to_thread(
        request.app.state.rag_bridge.request, "/workspaces", caller_headers=caller_headers(request)
    )


@router.get("/diagnostics")
async def diagnostics(request: Request):
    return await asyncio.to_thread(
        request.app.state.rag_bridge.request, "/diagnostics", caller_headers=caller_headers(request)
    )


@router.post("/workspaces/{wid}/analyze")
async def analyze(wid: str, request: Request):
    import re

    if not re.fullmatch(r"[a-f0-9]{32}", wid):
        raise HTTPException(422, "INVALID_WORKSPACE")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 65536:
            raise HTTPException(413, "MEETING_INPUT_TOO_LARGE")
    from pydantic import ValidationError

    try:
        body = AnalyzeInput.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "INVALID_MEETING_INPUT") from None
    require_owner(request.app, request.state.principal, body.session_id)
    bridge = request.app.state.rag_bridge
    if bridge.gate.locked():
        raise HTTPException(429, "LLM_BUSY")
    async with bridge.gate:
        payload = canonical_payload(request.app.state.service, body)
        result = await asyncio.to_thread(
            bridge.request,
            f"/workspaces/{wid}/meeting/analyze",
            payload,
            caller_headers=caller_headers(request),
        )
        # Never attach an answer to a deleted or edited utterance after the LLM finishes.
        current = canonical_payload(request.app.state.service, body)
        if [item["text"] for item in current["context"]] != [item["text"] for item in payload["context"]]:
            raise HTTPException(409, "STALE_UTTERANCE")
        return result


# The durable subscription transport lives separately from the legacy synchronous API.
from .subscriptions import router as subscription_router  # noqa: E402

router.include_router(subscription_router)
