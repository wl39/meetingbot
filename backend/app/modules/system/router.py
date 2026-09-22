from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/api/system", tags=["system"])


class ThemeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


@router.get("/theme")
async def theme(request: Request):
    return request.app.state.access.theme()


@router.post("/theme")
async def save_theme(body: ThemeInput, request: Request):
    return request.app.state.access.theme(body.color)


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: Literal["mlx", "faster-whisper"]
    model: Literal["small", "large-v3-turbo"]


@router.get("")
async def status(request: Request):
    settings = request.app.state.service.settings
    remote_url = settings.public_origin
    hostname = urlsplit(remote_url).hostname if remote_url else None
    # Report the administrator's configured endpoint, never a forwarded request host.
    # This metadata does not assert that Tailscale or a reverse proxy is reachable.
    return {
        **request.app.state.runtime.status(),
        "access": {
            "local_url": "http://127.0.0.1:8765",
            "remote_url": remote_url,
            "kind": "tailscale"
            if hostname and hostname.endswith(".ts.net")
            else "custom"
            if remote_url
            else None,
        },
    }


@router.post("/install", status_code=202)
async def install(selection: ModelSelection, request: Request):
    return request.app.state.runtime.submit("install", selection.engine, selection.model)


@router.post("/selection", status_code=202)
async def select(selection: ModelSelection, request: Request):
    return request.app.state.runtime.submit("selection", selection.engine, selection.model)


@router.get("/jobs/{job_id}")
async def job(job_id: str, request: Request):
    result = next((j for j in request.app.state.runtime.jobs if j["id"] == job_id), None)
    if result is None:
        raise HTTPException(404, "JOB_NOT_FOUND")
    return result
