"""Authenticated, bounded browser event ingestion; never accepts text or values."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/events")


class BrowserEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "click",
        "change",
        "submit",
        "navigation",
        "error",
        "unhandledrejection",
        "pagehide",
        "play",
        "pause",
        "ended",
        "seeked",
    ]
    page: Literal[
        "/",
        "/live",
        "/rag",
        "/settings",
        "/settings/speech",
        "/settings/rag",
        "/settings/ai",
        "/settings/updates",
        "/settings/access",
    ]
    target: str = Field(
        default="window",
        max_length=160,
        pattern=r"^(window|(?:[a-z]{1,16}:\d{1,4})(?:/[a-z]{1,16}:\d{1,4}){0,7})$",
    )


class BrowserEvents(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[BrowserEvent] = Field(min_length=1, max_length=50)


@router.post("", status_code=202)
async def record_events(body: BrowserEvents, request: Request):
    principal = request.state.principal
    if not request.app.state.access.consume(principal.subject, "browser-events", 20000, 200000):
        raise HTTPException(429, "EVENT_RATE_LIMIT")
    for event in body.events:
        request.app.state.audit.emit(
            "browser." + event.action, subject=principal.subject, role=principal.role, **event.model_dump()
        )
    return {"accepted": len(body.events)}
