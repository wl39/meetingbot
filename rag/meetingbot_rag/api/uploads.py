"""Bounded browser upload sessions and publication."""

from fastapi import APIRouter, Request

from ..uploads import UploadInput
from ..workspace_access import describe

router = APIRouter(prefix="/api/rag")


@router.get("/uploads/limits")
def upload_limits(request: Request):
    return request.app.state.core.uploads.limits()


@router.post("/uploads", status_code=201)
async def begin_upload(request: Request, body: UploadInput):
    principal = request.state.principal
    return await request.app.state.core.uploads.create(
        body, owner=None if principal.manages_data else principal.subject
    )


@router.get("/uploads/{sid}")
def upload_status(request: Request, sid: str):
    return request.app.state.core.uploads.get(sid)


@router.put("/uploads/{sid}/files/{fid}")
async def upload_file(sid: str, fid: str, request: Request):
    return await request.app.state.core.uploads.receive(sid, fid, request)


@router.post("/uploads/{sid}/commit")
async def commit_upload(request: Request, sid: str):
    core = request.app.state.core
    result = await core.uploads.commit(sid)
    result["workspace"] = describe(core, request.state.principal, result["workspace"])
    return result


@router.delete("/uploads/{sid}")
async def cancel_upload(request: Request, sid: str):
    return await request.app.state.core.uploads.cancel(sid)
