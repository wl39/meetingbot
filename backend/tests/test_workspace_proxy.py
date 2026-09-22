import io
from email.message import Message
from urllib.error import HTTPError, URLError

import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers

from app.main import create_app
from app.modules.meeting import workspace_proxy
from app.modules.stt.settings import Settings


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(_env_file=None, engine="fake", data_dir=tmp_path), FakeWorkers)
    with TestClient(app) as client:
        yield client


def upstream(monkeypatch, client, status=200, body=b'{"ok":true}', extra_headers=None):
    captured = []

    def open_request(request, timeout):
        captured.append(request)
        headers = Message()
        headers["Content-Type"] = "application/json"
        for key, value in (extra_headers or {}).items():
            headers[key] = value
        response = HTTPError(request.full_url, status, "upstream", headers, io.BytesIO(body))
        if status >= 400 or 300 <= status < 400:
            raise response
        return response

    monkeypatch.setattr(client.app.state.rag_bridge.opener, "open", open_request)
    return captured


def test_rag_auth_is_delegated_without_injecting_admin_key(client, monkeypatch):
    requests = upstream(monkeypatch, client, 401, b'{"error_code":"AUTH_REQUIRED"}')
    response = client.get("/api/rag/workspaces")
    assert response.status_code == 401
    assert response.json()["error_code"] == "AUTH_REQUIRED"
    assert not requests[0].has_header("Authorization")
    assert client.get("/api/stt/health").status_code == 401


def test_origin_is_checked_before_forwarding(client, monkeypatch):
    requests = upstream(monkeypatch, client)
    assert client.post("/api/rag/auth/login", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert requests == []


def test_login_cookie_and_csrf_forwarding(client, monkeypatch):
    requests = upstream(monkeypatch, client, extra_headers={"Set-Cookie": "rag_session=synthetic; HttpOnly; Path=/api/rag; SameSite=strict"})
    response = client.post("/api/rag/auth/login", json={"key": "synthetic"}, headers={"Origin": "http://127.0.0.1:8765"})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    client.patch("/api/rag/workspaces/synthetic", json={"name": "자료"}, headers={"Origin": "http://127.0.0.1:8765", "X-CSRF-Token": "csrf-synthetic"})
    assert requests[1].get_method() == "PATCH"
    assert requests[1].get_header("Cookie") == "rag_session=synthetic"
    assert requests[1].get_header("X-csrf-token") == "csrf-synthetic"
    assert requests[1].get_header("Origin") == "http://127.0.0.1:8766"


def test_missing_origin_is_not_fabricated(client, monkeypatch):
    requests = upstream(monkeypatch, client, 403, b'{"error_code":"CSRF_DENIED"}')
    assert client.post("/api/rag/workspaces", json={}).status_code == 403
    assert not requests[0].has_header("Origin")


def test_upload_query_and_caller_bearer_are_preserved(client, monkeypatch):
    requests = upstream(monkeypatch, client)
    content = bytes(range(256))
    response = client.put("/api/rag/uploads/abc/files/def?label=%ED%9A%8C%EC%9D%98", content=content, headers={"Content-Type": "application/octet-stream", "Authorization": "Bearer caller-key"})
    assert response.status_code == 200
    assert requests[0].data == content
    assert requests[0].full_url.endswith("/api/rag/uploads/abc/files/def?label=%ED%9A%8C%EC%9D%98")
    assert requests[0].get_header("Authorization") == "Bearer caller-key"


def test_redirects_are_not_followed(client, monkeypatch):
    upstream(monkeypatch, client, 307, extra_headers={"Location": "https://other.example"})
    assert client.get("/api/rag/workspaces").json()["detail"] == "RAG_REDIRECT_DENIED"


def test_async_question_acceptance_and_idempotency_key_are_preserved(client, monkeypatch):
    requests = upstream(monkeypatch, client, 202, b'{"request_id":"job-1","status":"queued"}')
    response = client.post("/api/rag/workspaces/synthetic/questions", json={"query": "question"},
                           headers={"Idempotency-Key": "same-submission"})
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert requests[0].get_header("Idempotency-key") == "same-submission"


def test_unavailable_service_returns_recoverable_error(client, monkeypatch):
    def unavailable(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(client.app.state.rag_bridge.opener, "open", unavailable)
    assert client.get("/api/rag/workspaces").status_code == 503


def test_proxy_limits_request_and_response(client, monkeypatch):
    monkeypatch.setattr(workspace_proxy, "MAX_BODY", 8)
    requests = upstream(monkeypatch, client, body=b"x" * 9)
    assert client.post("/api/rag/auth/login", content=b"x" * 9).status_code == 413
    assert requests == []
    assert client.get("/api/rag/workspaces").status_code == 502


@pytest.mark.parametrize("path", ["/", "/live", "/rag", "/rag/settings"])
def test_workspace_deep_links(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert '<div id="root">' in response.text
