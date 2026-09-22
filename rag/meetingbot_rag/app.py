"""RAG application factory and browser entry point."""

import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from meetingbot_access.audit import AuditLog, AuditMiddleware

from .adapters import LocalEmbedding
from .api import auth, history, management, meeting_jobs, sources, uploads, workspaces
from .http import configure_http
from .lifecycle import create_lifespan
from .settings import ROOT, Settings


def create_app(settings=None, model=None):
    s = settings or (Settings(_env_file=None) if os.environ.get("MEETINGBOT_DEMO_PROCESS") == "1" else Settings())
    s.prepare()
    model = model or LocalEmbedding(s)
    app = FastAPI(title="Meetingbot RAG", version="0.1.0", lifespan=create_lifespan(s, model))
    app.state.audit = AuditLog(s.data_dir / "logs", "rag")
    configure_http(app, s)
    app.add_middleware(AuditMiddleware, audit=app.state.audit, application=app)
    for router in (auth.router, sources.router, workspaces.router, uploads.router, management.router,
                   meeting_jobs.router, history.router):
        app.include_router(router)

    dist = ROOT / "frontend/dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/rag")
        @app.get("/rag/{rest:path}")
        def page(rest: str = ""):
            if s.workspace_url:
                return RedirectResponse(s.workspace_url + "/rag" + ("/" + rest if rest else ""), 307)
            return FileResponse(dist / "index.html")

    @app.get("/")
    def root_page():
        return RedirectResponse("/rag", 307)

    return app
