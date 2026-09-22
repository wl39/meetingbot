"""Personal and administrator query history endpoints."""

from typing import Literal

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/api/rag/history")
Scope = Literal["mine", "all"]


@router.get("")
def history(
    request: Request,
    scope: Scope = "mine",
    q: str = Query("", max_length=500),
    subject: str | None = Query(None, max_length=100),
    workspace_id: str | None = Query(None, max_length=100),
    kind: Literal["question", "search"] | None = None,
    since: float | None = Query(None, ge=0),
    until: float | None = Query(None, ge=0),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=1000000),
):
    return request.app.state.query_history.list(
        request.state.principal,
        scope,
        q=q,
        subject=subject,
        workspace_id=workspace_id,
        kind=kind,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/filters")
def filters(request: Request, scope: Scope = "mine"):
    return request.app.state.query_history.filters(request.state.principal, scope)


@router.get("/{record_id}")
def detail(request: Request, record_id: str, scope: Scope = "mine"):
    return request.app.state.query_history.get(request.state.principal, record_id, scope)
