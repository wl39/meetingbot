"""Session login, CSRF discovery, and logout."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from meetingbot_access import COOKIE, GUEST_SESSION_SECONDS

from ..schemas import Login
from ..sources import RagError

router = APIRouter(prefix="/api/rag")


@router.post("/auth/login")
def login(request: Request, body: Login):
    principal = request.app.state.access.key(body.key)
    if not principal:
        raise RagError("AUTH_REQUIRED", "접속 키가 올바르지 않습니다.", 401)
    token, principal = request.app.state.access.issue_session(principal)
    response = JSONResponse({"authenticated": True, "csrf": principal.csrf, "role": principal.role})
    response.set_cookie(
        "rag_session",
        token,
        httponly=True,
        secure=request.app.state.core.s.access_mode == "remote",
        samesite="strict",
        max_age=43200,
        path="/api/rag",
    )
    return response


@router.get("/auth/session")
def session(request: Request):
    principal = request.state.principal
    store = request.app.state.access
    token = None
    if not principal:
        if not store.consume("anonymous", "guest-session", 2000, 2000):
            raise RagError("RATE_LIMIT", "잠시 후 다시 시도하세요.", 429)
        token, principal = store.issue_session()
    elif principal.guest:
        token = request.cookies.get(COOKIE, "")
        store.renew_guest(token)
    request.state.principal = principal
    response = JSONResponse({"authenticated": True, "csrf": principal.csrf, "role": principal.role,
                             "account": store.profile(principal)})
    if token:
        response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/", max_age=GUEST_SESSION_SECONDS,
                            secure=request.app.state.core.s.access_mode == "remote")
    return response


@router.post("/auth/logout")
def logout(request: Request):
    token = request.cookies.get("rag_session", "")
    request.app.state.access.logout(request.cookies.get(COOKIE, ""))
    request.app.state.access.logout(token)
    response = JSONResponse({"authenticated": False})
    response.delete_cookie("rag_session", path="/api/rag")
    response.delete_cookie(COOKIE, path="/")
    return response
