"""HTTP limits, authentication, and the browser application's static entry points."""

from pathlib import Path

from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.access import authorize


class BodyLimit:
    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = min(self.limit, 32768) if scope.get("path") == "/api/events" else self.limit
        total = 0
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = limit + 1
        if length > limit:
            return await JSONResponse({"detail": "BODY_TOO_LARGE"}, 413)(scope, receive, send)

        async def bounded():
            nonlocal total
            message = await receive()
            total += len(message.get("body", b""))
            if total > limit:
                from starlette.exceptions import HTTPException

                raise HTTPException(413, "BODY_TOO_LARGE")
            return message

        await self.app(scope, bounded, send)


def configure_http(app, settings):
    app.add_middleware(BodyLimit, limit=settings.max_file_bytes + 1024 * 1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.middleware("http")
    async def authenticate(request, call_next):
        if (
            settings.public_origin
            and request.url.hostname in settings.redirect_hosts
            and request.url.scheme == "http"
        ):
            # Use a configured destination, never a client-supplied forwarded host.
            path = request.url.path
            query = "?" + request.url.query if request.url.query else ""
            return RedirectResponse(settings.public_origin + path + query, status_code=307)
        if request.url.path.startswith("/api/") and request.method != "OPTIONS":
            origin = request.headers.get("origin")
            if origin and origin not in settings.origins:
                return JSONResponse({"detail": "ORIGIN_DENIED"}, 403)
            try:
                authorize(request)
            except HTTPException as exc:
                return JSONResponse({"detail": exc.detail}, exc.status_code)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response


def mount_frontend(app):
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/audio-worklet.js")
        async def worklet():
            return FileResponse(dist / "audio-worklet.js", media_type="text/javascript")

        @app.get("/")
        @app.get("/live")
        @app.get("/settings")
        @app.get("/settings/{rest:path}")
        @app.get("/rag")
        @app.get("/rag/{rest:path}")
        async def index(rest: str = ""):
            return FileResponse(dist / "index.html")
