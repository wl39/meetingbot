"""STT application composition and stable Uvicorn factory entry point."""

import os

from fastapi import FastAPI
from meetingbot_access.audit import AuditLog, AuditMiddleware

from app.access import router as access_router
from app.http import configure_http, mount_frontend
from app.lifecycle import create_lifespan
from app.modules.meeting.router import router as meeting_router
from app.modules.meeting.workspace_proxy import router as workspace_router
from app.modules.stt.router import router as stt_router
from app.modules.stt.settings import Settings
from app.modules.stt.workers import Workers
from app.modules.system.catalog import load_selection
from app.modules.system.router import router as system_router
from app.telemetry import router as telemetry_router


def create_app(settings=None, worker_factory=Workers):
    settings = settings or (Settings(_env_file=None) if os.environ.get("MEETINGBOT_DEMO_PROCESS") == "1" else Settings())
    settings.prepare()
    load_selection(settings)
    app = FastAPI(title="Meetingbot STT", version="0.1.0", lifespan=create_lifespan(settings, worker_factory))
    app.state.audit = AuditLog(settings.data_dir / "logs", "stt")
    configure_http(app, settings)
    app.add_middleware(AuditMiddleware, audit=app.state.audit, application=app)
    for router in (access_router, telemetry_router, stt_router, meeting_router, workspace_router, system_router):
        app.include_router(router)
    mount_frontend(app)
    return app
