"""Compose STT transport features under the stable /api/stt entry point."""

from fastapi import APIRouter

from .routes import live, sessions, uploads
from .routes.dependencies import check_ready, get_session, resources

router = APIRouter(prefix="/api/stt")
for feature in (sessions.router, uploads.router, live.router):
    router.include_router(feature)

__all__ = ["check_ready", "get_session", "resources", "router"]
