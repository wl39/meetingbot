"""Authenticated durable meeting subscriptions, jobs and administrator policy."""

import secrets

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..meeting_jobs import JobInput
from ..meeting_policy import PolicyUpdate
from ..sources import RagError

router = APIRouter(prefix="/api/rag/workspaces/{wid}/meeting")


class SubscriptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class CancelInput(BaseModel):
    delete: bool = False


class SyncInput(BaseModel):
    utterance_ids: list[str] = Field(max_length=100000)
    generation: int = Field(default=0, ge=0)


class RetryInput(BaseModel):
    session_id: str = Field(min_length=1, max_length=128)


def internal(request):
    if request.headers.get("x-meeting-subscription") != "1":
        return False
    principal = request.state.principal
    supplied = request.headers.get("x-meeting-bridge-secret", "")
    if (
        principal.role != "superadmin"
        or principal.subject != "superadmin"
        or not supplied
        or not secrets.compare_digest(
            supplied.encode(), request.app.state.access.service_secret("meeting-subscription").encode()
        )
    ):
        # A user's installation key is not the internal worker identity. Reject
        # forged channels before any grant lookup, existing-job return or cleanup.
        raise RagError("ROLE_DENIED", status=403)
    return True


@router.get("/policy")
def policy(wid: str, request: Request):
    return request.app.state.meeting_jobs.policies.get(wid)


@router.put("/policy")
def save_policy(wid: str, body: PolicyUpdate, request: Request):
    service = request.app.state.meeting_jobs
    before = service.policies.get(wid)
    result = service.policies.save(wid, body, request.state.principal)
    service.policy_changed(wid, before)
    return result


@router.post("/sessions/{sid}/subscription")
def subscribe(wid: str, sid: str, body: SubscriptionInput, request: Request):
    service = request.app.state.meeting_jobs
    result = service.subscription(wid, sid, request.state.principal, body.enabled, body.revision_id)
    return {**result, "policy_version": service.policies.get(wid)["version"]}


@router.post("/sessions/{sid}/cancel")
def cancel(wid: str, sid: str, body: CancelInput, request: Request):
    return request.app.state.meeting_jobs.cancel(
        wid,
        sid,
        request.state.principal,
        internal(request),
        body.delete,
    )


@router.post("/sessions/{sid}/sync")
def sync(wid: str, sid: str, body: SyncInput, request: Request):
    service = request.app.state.meeting_jobs
    result = service.sync(
        wid, sid, body.utterance_ids, request.state.principal, internal(request), body.generation
    )
    return {**result, "policy_version": service.policies.get(wid)["version"]}


@router.post("/jobs", status_code=202)
def enqueue(wid: str, body: JobInput, request: Request):
    return request.app.state.meeting_jobs.enqueue(wid, body, request.state.principal, internal(request))


@router.get("/jobs")
def jobs(
    wid: str,
    session_id: str,
    request: Request,
    cursor: str | None = Query(None, max_length=128),
    limit: int = Query(15, ge=1, le=50),
    include_anchor: bool = False,
):
    return request.app.state.meeting_jobs.list(
        wid, session_id, request.state.principal, cursor, limit, include_anchor
    )


@router.post("/jobs/{jid}/retry")
def retry(wid: str, jid: str, body: RetryInput, request: Request):
    return request.app.state.meeting_jobs.retry(wid, body.session_id, jid, request.state.principal)
