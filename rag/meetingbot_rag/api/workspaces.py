"""Workspace, revision, indexing, search, and evidence endpoints."""

import json
import re
from typing import Literal

from fastapi import APIRouter, Query, Request

from ..meeting import MeetingInput
from ..schemas import IndexInput, RevisionPatch, SearchInput, SourceInput, WorkspaceInput, WorkspacePatch
from ..services import job_public
from ..sources import RagError
from ..uploads import public_source
from ..workspace_access import describe, visible
from ..workspace_guides import GuideUpdate

router = APIRouter(prefix="/api/rag")


@router.get("/workspaces")
def workspaces(request: Request):
    core, principal = request.app.state.core, request.state.principal
    return [describe(core, principal, w) for w in core.workspaces.list() if visible(core, principal, w["id"])]


@router.post("/workspaces", status_code=201)
def create_workspace(request: Request, body: WorkspaceInput):
    public_source(body.root_id)
    if not body.name.strip():
        raise RagError("NAME_REQUIRED", "이름을 입력하세요.")
    return request.app.state.core.workspaces.create(**body.model_dump())


@router.get("/workspaces/{wid}")
def workspace(request: Request, wid: str):
    core = request.app.state.core
    return describe(core, request.state.principal, core.workspaces.get(wid))


@router.patch("/workspaces/{wid}")
def patch_workspace(request: Request, wid: str, body: WorkspacePatch):
    c = request.app.state.core
    with c.workspaces.locks[wid], c.db.transaction():
        c.workspaces.get(wid)
        if body.name is not None:
            c.db.execute("UPDATE workspaces SET name=? WHERE id=?", (body.name, wid))
        if body.description is not None:
            c.db.execute("UPDATE workspaces SET description=? WHERE id=?", (body.description, wid))
        if body.external_llm_approved is not None:
            if body.external_llm_approved and (
                not request.app.state.answer.policy()["global_allowed"]
                or body.provider_id != request.app.state.answer.policy()["provider_id"]
            ):
                raise RagError("LLM_POLICY_NOT_READY", "서버의 전역 허용 및 연결 설정을 먼저 확인하세요.")
            c.db.execute(
                "UPDATE workspaces SET consent=? WHERE id=?",
                (
                    request.app.state.answer.policy()["provider_id"] if body.external_llm_approved else None,
                    wid,
                ),
            )
    return describe(c, request.state.principal, c.workspaces.get(wid))


@router.delete("/workspaces/{wid}")
def delete_workspace(request: Request, wid: str):
    return request.app.state.core.delete(wid)


@router.get("/workspaces/{wid}/guide")
def workspace_guide(request: Request, wid: str):
    return request.app.state.core.guides.get(wid)


@router.put("/workspaces/{wid}/guide")
def save_workspace_guide(request: Request, wid: str, body: GuideUpdate):
    return request.app.state.core.guides.save(wid, body)


@router.post("/workspaces/{wid}/sources", status_code=201)
def source(request: Request, wid: str, body: SourceInput):
    public_source(body.root_id)
    return request.app.state.core.workspaces.source(wid, **body.model_dump())


@router.get("/workspaces/{wid}/revisions")
def revisions(request: Request, wid: str):
    c = request.app.state.core
    c.workspaces.get(wid)
    return [
        {**r, "manifest": json.loads(r["manifest"] or "{}"), "config": json.loads(r["config"] or "{}")}
        for r in c.db.all("SELECT * FROM revisions WHERE workspace_id=? ORDER BY created_at DESC", (wid,))
    ]


@router.patch("/workspaces/{wid}/revisions/{rid}")
def pin_revision(request: Request, wid: str, rid: str, body: RevisionPatch):
    return request.app.state.core.revisions.pin(wid, rid, body.pinned)


@router.delete("/workspaces/{wid}/revisions/{rid}")
def delete_revision(request: Request, wid: str, rid: str):
    return request.app.state.core.revisions.remove(wid, rid)


@router.get("/workspaces/{wid}/documents")
def documents(
    request: Request,
    wid: str,
    revision_id: str | None = None,
    relative_path: str | None = None,
    metadata_only: bool = False,
):
    c = request.app.state.core
    if relative_path is not None:
        return c.evidence.document(wid, relative_path, revision_id, metadata_only)
    _, rev = c.revisions.resolve(wid, revision_id)
    return {"workspace_id": wid, "revision_id": rev["id"], "files": json.loads(rev["manifest"])["files"]}


@router.get("/workspaces/{wid}/source-preview")
def source_preview(request: Request, wid: str, relative_path: str = Query(max_length=2048),
                   sheet: str | None = Query(None, max_length=200), page: int | None = Query(None, ge=0),
                   source_offset: int | None = Query(None, ge=0)):
    if not request.state.principal.manages_data:
        raise RagError("FORBIDDEN", status=403)
    return request.app.state.core.evidence.source_preview(wid, relative_path, sheet, page, source_offset)


@router.post("/workspaces/{wid}/index-jobs", status_code=202)
def index(wid: str, request: Request, body: IndexInput | None = None):
    key = request.headers.get("idempotency-key")
    if key and not re.fullmatch(r"[\w-]{1,100}", key):
        raise RagError("INVALID_IDEMPOTENCY_KEY")
    return request.app.state.core.ingestion.create(wid, idempotency_key=key, allow_review=bool(body and body.allow_review))


@router.get("/workspaces/{wid}/index-jobs/{jid}")
def job(request: Request, wid: str, jid: str):
    c = request.app.state.core
    c.workspaces.get(wid)
    found = c.db.one("SELECT * FROM jobs WHERE id=? AND workspace_id=?", (jid, wid))
    if not found:
        raise RagError("NOT_FOUND", status=404)
    return job_public(found)


@router.post("/workspaces/{wid}/index-jobs/{jid}/cancel")
def cancel(request: Request, wid: str, jid: str):
    current = job(request, wid, jid)
    if current["state"] in {"QUEUED", "RUNNING"}:
        request.app.state.core.db.execute(
            "UPDATE jobs SET cancel=1 WHERE id=? AND workspace_id=?", (jid, wid)
        )
    return job(request, wid, jid)


@router.post("/workspaces/{wid}/search")
def search(request: Request, wid: str, body: SearchInput):
    return request.app.state.query_history.run(
        wid, body, request.state.principal, "search",
        lambda: request.app.state.core.retrieval.search(wid, **body.model_dump()),
    )


@router.post("/workspaces/{wid}/questions", status_code=202)
def questions(request: Request, wid: str, body: SearchInput):
    key = request.headers.get("idempotency-key")
    if key and not re.fullmatch(r"[\w-]{1,100}", key):
        raise RagError("INVALID_IDEMPOTENCY_KEY")
    return request.app.state.question_jobs.enqueue(wid, body, request.state.principal, key)


@router.post("/workspaces/{wid}/meeting/analyze")
def meeting_analyze(request: Request, wid: str, body: MeetingInput):
    request.app.state.meeting_jobs._session_access(body.session_id, request.state.principal)
    return request.app.state.meeting.analyze(wid, body)


@router.get("/workspaces/{wid}/questions")
def history(request: Request, wid: str):
    c = request.app.state.core
    c.workspaces.get(wid)
    return request.app.state.query_history.recent(request.state.principal, wid)


@router.get("/workspaces/{wid}/evidence/{eid}")
def evidence(
    request: Request,
    wid: str,
    eid: str,
    revision_id: str,
    view: Literal["preview", "document", "source"] | None = None,
    page: int | None = Query(None, ge=0),
    anchor: str | None = Query(None, max_length=2048),
    outline_offset: int = Query(0, ge=0),
    source_offset: int | None = Query(None, ge=0),
    sheet: str | None = Query(None, max_length=200),
):
    return request.app.state.core.evidence.get(
        wid,
        eid,
        revision_id,
        view=view,
        page=page,
        anchor=anchor,
        outline_offset=outline_offset,
        source_offset=source_offset,
        sheet=sheet,
    )
