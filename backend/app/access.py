"""Public demo bootstrap, role management and STT record ownership."""

import re
import secrets

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from meetingbot_access import COOKIE, GUEST_SESSION_SECONDS, ROLES, rag_allowed
from meetingbot_access.audit import request_context
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/access")


def identity(connection):
    store = connection.app.state.access
    settings = connection.app.state.service.settings
    authorization = connection.headers.get("authorization", "")
    if authorization.strip():
        return store.key(authorization.removeprefix("Bearer "))
    return store.session(connection.cookies.get(COOKIE, ""), allow_guest=settings.demo_mode or settings.keyless_login)


def require_owner(app, principal, sid):
    # Managing shared documents does not grant access to somebody else's audio.
    if not principal or app.state.access.owner(sid) != principal.subject:
        raise HTTPException(404, "SESSION_NOT_FOUND")


def register_session(request, session):
    request.app.state.access.owner(session["id"], request.state.principal.subject)
    return session


def prepare_options(request, options):
    s = request.app.state.service.settings
    if s.demo_mode:
        options.retain_audio = False
        if not request.app.state.access.consume(request.state.principal.subject, "transcription",
                                               s.demo_jobs_per_visitor, s.demo_daily_jobs):
            raise HTTPException(429, "DEMO_DAILY_LIMIT")


def authorize(request):
    principal = identity(request)
    request.state.principal = principal
    if principal:
        request_context.set({**(request_context.get() or {}), "subject": principal.subject, "role": principal.role})
    path = request.url.path.rstrip("/")
    if path == "/api/access/session" and request.method == "GET":
        return
    if path == "/api/system/theme" and request.method == "GET":
        return
    # The RAG service validates its cookie/bearer as well, including direct access.
    if path.startswith("/api/rag/"):
        if principal and not rag_allowed(principal.role, request.method, path):
            raise HTTPException(403, "ROLE_DENIED")
        return
    if not principal:
        raise HTTPException(401, "LOCAL_AUTH_REQUIRED")
    if not request.headers.get("authorization", "").strip() and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not request.headers.get("origin") or not secrets.compare_digest(
            request.headers.get("x-csrf-token", ""), principal.csrf
        ):
            raise HTTPException(403, "CSRF_DENIED")
    if path == "/api/events" and request.method == "POST":
        return
    if path.startswith("/api/access/"):
        if path != "/api/access/logout" and principal.role != "superadmin":
            raise HTTPException(403, "ROLE_DENIED")
        return
    if path == "/api/system" or path.startswith("/api/system/"):
        if principal.role != "superadmin":
            raise HTTPException(403, "ROLE_DENIED")
        if request.app.state.service.settings.demo_mode and path == "/api/system/install":
            raise HTTPException(409, "DEMO_INSTALL_DISABLED")
        return
    if not path.startswith("/api/stt/"):
        raise HTTPException(403, "ROLE_DENIED")
    match = re.match(r"/api/stt/(?:sessions|meeting/sessions)/([^/]+)(?:/|$)", path)
    upload = re.match(r"/api/stt/files/([^/]+)/(?:chunks/|finish$)", path)
    if match or upload:
        require_owner(request.app, principal, (match or upload)[1])
    job = re.fullmatch(r"/api/stt/jobs/([^/]+)", path)
    if job:
        record = request.app.state.service.repo.get_job(job[1])
        if not record:
            raise HTTPException(404, "JOB_NOT_FOUND")
        require_owner(request.app, principal, record["session_id"])


@router.get("/session")
async def session(request: Request):
    s = request.app.state.service.settings
    principal = request.state.principal
    cookie = None
    if not principal and (s.demo_mode or s.keyless_login) and not request.headers.get("authorization", "").strip():
        if not request.app.state.access.consume("anonymous", "guest-session", 2000, 2000):
            raise HTTPException(429, "DEMO_DAILY_LIMIT")
        cookie, principal = request.app.state.access.issue_session()
        request.state.principal = principal
    elif principal and principal.guest:
        cookie = request.cookies.get(COOKIE, "")
        request.app.state.access.renew_guest(cookie)
    result = JSONResponse({
        "authenticated": principal is not None,
        "role": principal.role if principal else None,
        "account": request.app.state.access.profile(principal) if principal else None,
        "demo": s.demo_mode,
        "keyless": s.keyless_login or s.demo_mode,
        "csrf": principal.csrf if principal else "",
        "limits": {"seconds": s.max_file_seconds, "file_mb": s.max_file_bytes // (1024 * 1024),
                   "jobs_per_visitor": s.demo_jobs_per_visitor, "jobs_daily": s.demo_daily_jobs},
    })
    if cookie:
        result.set_cookie(COOKIE, cookie, httponly=True, samesite="strict",
                          secure=bool(s.public_origin), max_age=GUEST_SESSION_SECONDS, path="/")
    return result


@router.post("/logout")
async def logout(request: Request):
    request.app.state.access.logout(request.cookies.get(COOKIE, ""))
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(COOKIE, path="/")
    return response


class KeyInput(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    role: str


@router.get("/keys")
async def keys(request: Request):
    return {"keys": request.app.state.access.keys(), "roles": ROLES}


@router.post("/keys", status_code=201)
async def issue_key(body: KeyInput, request: Request):
    try:
        return request.app.state.access.issue_key(body.label, body.role)
    except ValueError:
        raise HTTPException(422, "INVALID_ACCESS_KEY") from None


@router.delete("/keys/{kid}")
async def revoke_key(kid: str, request: Request):
    if not request.app.state.access.revoke(kid):
        raise HTTPException(404, "KEY_NOT_FOUND")
    return {"revoked": True}
