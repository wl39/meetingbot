"""Server source browsing and asynchronous previews."""

import json

from fastapi import APIRouter, Query, Request

from ..schemas import SourceInput
from ..services import job_public
from ..sources import RagError
from ..uploads import public_source

router = APIRouter(prefix="/api/rag")


@router.get("/source-roots")
def roots(request: Request):
    roots, version = request.app.state.core.sources.roots()
    return {
        "roots": [{"id": r["id"], "label": r["label"]} for r in roots],
        "setup_required": not roots,
        "access_scope_version": version,
    }


@router.get("/source-roots/{root_id}/entries")
def entries(
    request: Request,
    root_id: str,
    relative_path: str = "",
    cursor: int = Query(default=0, ge=0, le=20000),
    filter: str = Query(default="", max_length=100),
):
    public_source(root_id)
    return request.app.state.core.sources.entries(root_id, relative_path, cursor, filter)


@router.post("/source-previews", status_code=202)
def preview(request: Request, body: SourceInput):
    public_source(body.root_id)
    return request.app.state.core.ingestion.create(payload=body.model_dump())


@router.get("/source-previews/{jid}")
def preview_job(request: Request, jid: str):
    job = request.app.state.core.db.one("SELECT * FROM jobs WHERE id=? AND workspace_id IS NULL", (jid,))
    if not job:
        raise RagError("NOT_FOUND", status=404)
    source = json.loads(job["payload"])
    request.app.state.core.sources.validate(source["root_id"], source["relative_path"])
    return job_public(job)
