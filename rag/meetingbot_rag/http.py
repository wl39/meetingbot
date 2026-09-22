"""HTTP limits, authentication, origin checks, and safe error responses."""

import re
import secrets
import threading
import time
from collections import defaultdict, deque

from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from meetingbot_access import COOKIE, digest, rag_allowed
from meetingbot_access.audit import request_context

from .db import uid
from .sources import RagError
from .workspace_access import denied_status


class BodyLimit:
    def __init__(self, app, max_file_bytes):
        self.app, self.max_file_bytes = app, max_file_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0
        path = scope.get("path", "")
        limit = 65536
        if path == "/api/rag/uploads" and scope["method"] == "POST":
            limit = 8 * 1024 * 1024
        elif re.fullmatch(r"/api/rag/workspaces/[a-f0-9]{32}/meeting/sessions/[^/]+/sync", path):
            limit = 8 * 1024 * 1024
        elif re.fullmatch(r"/api/rag/workspaces/[a-f0-9]{32}/meeting/jobs", path):
            # Full bounded Korean source + five complete context utterances.
            limit = 512 * 1024
        elif re.fullmatch(r"/api/rag/uploads/[a-f0-9]{32}/files/[a-f0-9]{32}", path):
            limit = self.max_file_bytes

        async def bounded():
            nonlocal size
            message = await receive()
            size += len(message.get("body", b""))
            if size > limit:
                from starlette.exceptions import HTTPException

                raise HTTPException(413, "BODY_TOO_LARGE")
            return message

        return await self.app(scope, bounded, send)


def configure_http(app, s):
    app.add_middleware(BodyLimit, max_file_bytes=s.max_file_bytes)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=s.allowed_hosts)
    attempts = defaultdict(deque)
    rate_lock = threading.Lock()

    @app.exception_handler(RagError)
    async def error_handler(request, error):
        return JSONResponse(
            {"error_code": error.code, "message": error.message, "request_id": uid()}, error.status
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse(
            {
                "error_code": "INVALID_REQUEST",
                "message": "입력 형식 또는 길이를 확인하세요.",
                "request_id": uid(),
            },
            422,
        )

    @app.middleware("http")
    async def auth(request, call_next):
        path = request.url.path
        origin = request.headers.get("origin")
        hostname = request.url.hostname
        if hostname not in s.allowed_hosts:
            return JSONResponse({"error_code": "HOST_DENIED"}, 400)
        if s.public_origin and hostname in s.redirect_hosts and request.url.scheme == "http":
            return RedirectResponse(
                s.public_origin + path + ("?" + request.url.query if request.url.query else ""), 307
            )
        if (
            s.access_mode == "remote"
            and hostname not in {"127.0.0.1", "localhost", "testserver"}
            and request.url.scheme != "https"
        ):
            return JSONResponse({"error_code": "HTTPS_REQUIRED"}, 403)
        if path.startswith("/api/"):
            if origin and origin not in s.origins:
                return JSONResponse({"error_code": "ORIGIN_DENIED"}, 403)
            rate_key = (
                (request.client.host if request.client else "local") if path.endswith("/login") else digest(
                    request.headers.get("authorization", "") or request.cookies.get(COOKIE, "")
                    or request.cookies.get("rag_session", "") or "anonymous"),
                "login"
                if path.endswith("/login")
                else (
                    "upload"
                    if request.method == "PUT"
                    and re.fullmatch(r"/api/rag/uploads/[a-f0-9]{32}/files/[a-f0-9]{32}", path)
                    else "api"
                ),
            )
            now = time.monotonic()
            with rate_lock:
                if len(attempts) > 2000:
                    for expired in [key for key, values in attempts.items() if not values or values[-1] < now - 60]:
                        del attempts[expired]
                    if len(attempts) > 2000:
                        return JSONResponse({"error_code": "RATE_LIMIT"}, 429)
                queue = attempts[rate_key]
                while queue and queue[0] < now - 60:
                    queue.popleft()
                cap = {"login": 10, "api": 240, "upload": 6000}[rate_key[1]]
                if len(queue) >= cap:
                    return JSONResponse(
                        {"error_code": "RATE_LIMIT", "message": "잠시 후 다시 시도하세요."}, 429
                    )
                queue.append(now)
            if path != "/api/rag/auth/login":
                token = request.headers.get("authorization", "").removeprefix("Bearer ")
                bearer = app.state.access.key(token) if token else None
                session = app.state.access.session(
                    request.cookies.get("rag_session", "") or request.cookies.get(COOKIE, ""),
                    allow_guest=s.demo_mode or s.keyless_login,
                ) if not token else None
                principal = bearer or session
                request.state.principal = principal
                if principal:
                    request_context.set({**(request_context.get() or {}), "subject": principal.subject, "role": principal.role})
                if not principal and path == "/api/rag/auth/session" and request.method == "GET" and not token and (s.keyless_login or s.demo_mode):
                    return await call_next(request)
                if not principal:
                    return JSONResponse(
                        {"error_code": "AUTH_REQUIRED", "message": "접속 키로 로그인하세요."}, 401
                    )
                if not bearer and request.method not in {"GET", "HEAD", "OPTIONS"}:
                    if not origin or not secrets.compare_digest(
                        request.headers.get("x-csrf-token", ""), session.csrf
                    ):
                        return JSONResponse({"error_code": "CSRF_DENIED"}, 403)
                if not rag_allowed(principal.role, request.method, path.rstrip("/")):
                    return JSONResponse({"error_code": "ROLE_DENIED", "message": "이 기능은 관리 권한이 필요합니다."}, 403)
                denied = denied_status(app.state.core, principal, request.method, path.rstrip("/"))
                if denied:
                    return JSONResponse({"error_code": "NOT_FOUND" if denied == 404 else "ROLE_DENIED",
                                         "message": "자료를 찾을 수 없거나 접근 권한이 없습니다."}, denied)
                if s.demo_mode and request.method == "POST" and re.fullmatch(
                    r"/api/rag/workspaces/[a-f0-9]{32}/(?:questions|meeting/analyze)", path
                ):
                    if not app.state.access.consume(principal.subject, "ai", 20, 300):
                        return JSONResponse({"error_code": "DEMO_DAILY_LIMIT", "message": "오늘의 데모 AI 사용 한도에 도달했습니다."}, 429)
                request.state.session = session
                request.state.principal = principal
                if s.demo_mode and request.method == "POST" and path.endswith("/search"):
                    if not app.state.access.consume(principal.subject, "search", 100, 3000):
                        return JSONResponse({"error_code": "DEMO_DAILY_LIMIT"}, 429)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "Cache-Control": "no-store",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
        return response
