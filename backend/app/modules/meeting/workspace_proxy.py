"""Same-origin RAG access with the caller's existing cookie/bearer authentication."""

import asyncio
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

router = APIRouter(prefix="/api/rag")
MAX_BODY = 32 * 1024 * 1024


def forward(bridge, method, path, query, headers, body):
    # The origin is validated as loopback by Settings. No redirects or environment proxies.
    url = bridge.settings.rag_base_url + "/api/rag/" + path
    if query:
        url += "?" + query
    request = URLRequest(url, data=body or None, headers=headers, method=method)
    try:
        response = bridge.opener.open(request, timeout=150)
    except HTTPError as error:
        response = error
    except (TimeoutError, socket.timeout):
        raise HTTPException(504, "RAG_TIMEOUT") from None
    except (URLError, OSError):
        raise HTTPException(503, "RAG_UNAVAILABLE") from None
    try:
        with response:
            if 300 <= response.code < 400:
                raise HTTPException(502, "RAG_REDIRECT_DENIED")
            content = response.read(MAX_BODY + 1)
            if len(content) > MAX_BODY:
                raise HTTPException(502, "RAG_RESPONSE_TOO_LARGE")
            result = Response(content, status_code=response.code)
            for name in ("Content-Type", "Set-Cookie", "Retry-After"):
                for value in response.headers.get_all(name, []):
                    result.headers.append(name, value)
            return result
    except (TimeoutError, socket.timeout):
        raise HTTPException(504, "RAG_TIMEOUT") from None
    except OSError:
        raise HTTPException(503, "RAG_UNAVAILABLE") from None


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def rag_request(path: str, request: Request):
    # Use the original encoded suffix so Unicode, query values and path separators stay intact.
    raw_path = request.scope["raw_path"].decode("ascii").split("?", 1)[0]
    suffix = raw_path.removeprefix("/api/rag/")
    if any(part in {".", ".."} for part in path.split("/")):
        raise HTTPException(400, "INVALID_RAG_PATH")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            raise HTTPException(413, "BODY_TOO_LARGE")
    bridge = request.app.state.rag_bridge
    headers = {
        name: request.headers[name]
        for name in ("Authorization", "Cookie", "Content-Type", "X-CSRF-Token", "Idempotency-Key")
        if name in request.headers
    }
    headers["X-Request-ID"] = request.state.request_id
    # The outer middleware checks the browser origin. Preserve its presence for RAG's CSRF check.
    if request.headers.get("origin"):
        headers["Origin"] = bridge.settings.rag_base_url
    return await asyncio.to_thread(
        forward, bridge, request.method, suffix,
        request.scope["query_string"].decode("ascii"), headers, bytes(body),
    )
