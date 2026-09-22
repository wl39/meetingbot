import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_api import FakeWorkers

from app.contracts.utterance import UtteranceEvent
from app.main import create_app
from app.modules.meeting.router import MAX_RESPONSE, RagBridge
from app.modules.stt.settings import Settings

WID = "a" * 32
PATH = f"/api/stt/meeting/workspaces/{WID}/analyze"


@pytest.fixture
def meeting_client(tmp_path):
    settings = Settings(_env_file=None, engine="fake", data_dir=tmp_path)
    app = create_app(settings, FakeWorkers)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        yield client


def transcript(client):
    session = client.post("/api/stt/sessions", json={}).json()
    utterances = [
        UtteranceEvent(
            session_id=session["id"],
            input_mode="microphone",
            start_ms=i * 2000,
            end_ms=i * 2000 + 1000,
            text=f"앞선 문맥 {i}",
        ).model_dump()
        for i in range(5)
    ]
    utterances[-1]["text"] = "로그 기록은 서버에 45일 남아요."
    session["utterances"] = utterances
    client.app.state.service.repo.save(session)
    return {
        "session_id": session["id"],
        "utterance": {
            key: utterances[-1][key]
            for key in ("utterance_id", "revision", "text", "status", "speaker_id", "start_ms", "end_ms")
        },
        "context": [{"text": "클라이언트가 바꾼 문맥", "speaker_id": "spoofed"}],
    }


@pytest.mark.parametrize("route", ["/config", "/workspaces", "/diagnostics"])
def test_bridge_gets_require_stt_auth_and_allowed_origin(meeting_client, monkeypatch, route):
    client = meeting_client
    monkeypatch.setattr(client.app.state.rag_bridge, "request", lambda *args, **kwargs: {"ok": True})
    path = "/api/stt/meeting" + route
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get(path, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get(path, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 200


def test_canonical_source_and_speaker_only_revision(meeting_client, monkeypatch):
    client = meeting_client
    body = transcript(client)
    session = client.app.state.service.repo.get(body["session_id"])
    current = session["utterances"][-1]
    current.update(revision=2, speaker_id="speaker-A", speaker_status="assigned")
    session["utterances"][1]["text"] = "문" * 1800
    client.app.state.service.repo.save(session)
    captured = []

    def upstream(path, payload, caller_headers=None):
        assert caller_headers["Authorization"] == "Bearer " + client.app.state.token
        captured.append((path, payload))
        return {"status": "complete", "alerts": []}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    response = client.post(PATH, json=body)
    assert response.status_code == 200, response.text
    path, payload = captured[0]
    assert path == f"/workspaces/{WID}/meeting/analyze"
    assert payload["utterance"]["revision"] == 2
    assert payload["utterance"]["speaker_id"] == "speaker-A"
    assert [item["text"] for item in payload["context"]] == ["문" * 1500, "앞선 문맥 2", "앞선 문맥 3"]
    assert "spoofed" not in json.dumps(payload)


@pytest.mark.parametrize("change", ["text", "start_ms", "end_ms", "partial", "missing", "session"])
def test_stale_or_unstable_source_never_reaches_rag(meeting_client, monkeypatch, change):
    client = meeting_client
    body = transcript(client)
    session = client.app.state.service.repo.get(body["session_id"])
    if change in {"text", "start_ms", "end_ms"}:
        body["utterance"][change] = "다른 발화" if change == "text" else 1
    elif change == "partial":
        session["utterances"][-1]["status"] = "partial"
    elif change == "missing":
        session["utterances"].pop()
    else:
        body["session_id"] = "missing-session"
    client.app.state.service.repo.save(session)

    def forbidden(*args, **kwargs):
        pytest.fail("A stale utterance must not reach the RAG service")

    monkeypatch.setattr(client.app.state.rag_bridge, "request", forbidden)
    response = client.post(PATH, json=body)
    assert response.status_code == (404 if change == "session" else 409)


@pytest.mark.parametrize("deleted", [False, True])
def test_late_result_is_rejected_after_source_edit_or_deletion(meeting_client, monkeypatch, deleted):
    client = meeting_client
    body = transcript(client)
    repo = client.app.state.service.repo

    def upstream(*args, **kwargs):
        if deleted:
            repo.delete(body["session_id"])
        else:
            session = repo.get(body["session_id"])
            session["utterances"][-1]["text"] = "로그 기록은 90일 남아요."
            repo.save(session)
        return {"alerts": [{"title": "오래된 발화의 정정"}]}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    response = client.post(PATH, json=body)
    assert response.status_code == (404 if deleted else 409)
    assert "alerts" not in response.json()


@pytest.mark.parametrize("change", ["text", "deleted", "speaker"])
def test_late_result_tracks_the_context_used_for_analysis(meeting_client, monkeypatch, change):
    client = meeting_client
    body = transcript(client)
    repo = client.app.state.service.repo

    def upstream(*args, **kwargs):
        session = repo.get(body["session_id"])
        if change == "deleted":
            session["utterances"].pop(-2)
        elif change == "text":
            session["utterances"][-2]["text"] = "앞 문맥은 운영서버가 아니라 개발서버입니다."
        else:
            session["utterances"][-2]["speaker_id"] = "speaker-B"
        repo.save(session)
        return {"status": "popup"}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    response = client.post(PATH, json=body)
    assert response.status_code == (200 if change == "speaker" else 409)


def test_analyze_auth_validation_limits_and_gate(meeting_client, monkeypatch):
    client = meeting_client
    body = transcript(client)
    assert client.post(PATH, json=body, headers={"Authorization": ""}).status_code == 401
    assert client.post(PATH, json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(PATH.replace(WID, "bad-workspace"), json=body).status_code == 422
    assert client.post(PATH, content=b"{" + b" " * 65536).status_code == 413
    assert client.post(PATH, content=b"not json").status_code == 422
    oversized = {**body, "utterance": {**body["utterance"], "text": "a" * 4001}}
    assert client.post(PATH, json=oversized).status_code == 422
    partial = {**body, "utterance": {**body["utterance"], "status": "partial"}}
    assert client.post(PATH, json=partial).status_code == 422
    started, release = threading.Event(), threading.Event()

    def upstream(*args, **kwargs):
        started.set()
        assert release.wait(5), "Test did not release upstream request"
        raise HTTPException(503, "RAG_UNAVAILABLE")

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.post, PATH, json=body)
        try:
            assert started.wait(5)
            busy = client.post(PATH, json=body)
            assert busy.status_code == 429
            assert busy.json()["detail"] == "LLM_BUSY"
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 503
    monkeypatch.setattr(client.app.state.rag_bridge, "request", lambda *args, **kwargs: {"alerts": []})
    assert client.post(PATH, json=body).status_code == 200


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:8766",
        "http://example.com:8766",
        "http://127.0.0.1",
        "http://user:secret@127.0.0.1:8766",
        "http://127.0.0.1:8766/other",
        "http://127.0.0.1:8766?key=value",
        "http://127.0.0.1:8766#fragment",
    ],
)
def test_bridge_only_accepts_loopback_origin(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rag_base_url=url)


def bridge(tmp_path):
    token = tmp_path / "rag-token"
    token.write_text("separate-test-rag-credential")
    return RagBridge(Settings(_env_file=None, data_dir=tmp_path, rag_token_file=token))


def test_separate_rag_credential_and_post_timeout(tmp_path):
    service = bridge(tmp_path)
    captured = []

    class Response(io.BytesIO):
        status = 200

    def open_request(request, timeout):
        captured.append((request, timeout))
        return Response(b'{"alerts":[]}')

    service.opener = SimpleNamespace(open=open_request)
    assert service.request("/workspaces", {"text": "발화"}) == {"alerts": []}
    request, timeout = captured[0]
    assert request.get_header("Authorization") == "Bearer separate-test-rag-credential"
    assert request.full_url == "http://127.0.0.1:8766/api/rag/workspaces"
    assert json.loads(request.data) == {"text": "발화"}
    assert timeout >= 40


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (URLError("connection refused"), 503, "RAG_UNAVAILABLE"),
        (URLError(TimeoutError()), 504, "RAG_TIMEOUT"),
        (TimeoutError(), 504, "RAG_TIMEOUT"),
    ],
)
def test_bridge_network_error_codes(tmp_path, failure, status, code):
    service = bridge(tmp_path)

    def fail(*args, **kwargs):
        raise failure

    service.opener = SimpleNamespace(open=fail)
    with pytest.raises(HTTPException) as error:
        service.request("/diagnostics")
    assert (error.value.status_code, error.value.detail) == (status, code)


@pytest.mark.parametrize(
    "raw,code", [(b"not json", "RAG_INVALID_RESPONSE"), (b"x" * (MAX_RESPONSE + 1), "RAG_RESPONSE_TOO_LARGE")]
)
def test_bridge_rejects_invalid_and_oversized_response(tmp_path, raw, code):
    service = bridge(tmp_path)

    class Response(io.BytesIO):
        status = 200

    service.opener = SimpleNamespace(open=lambda *args, **kwargs: Response(raw))
    with pytest.raises(HTTPException) as error:
        service.request("/diagnostics")
    assert (error.value.status_code, error.value.detail) == (502, code)


def test_bridge_sanitizes_upstream_errors_and_missing_credential(tmp_path):
    service = bridge(tmp_path)

    def upstream(*args, **kwargs):
        raise HTTPError(
            "http://127.0.0.1:8766",
            403,
            "Denied",
            {},
            io.BytesIO(
                json.dumps(
                    {"error_code": "EXTERNAL_LLM_NOT_APPROVED", "message": "upstream internals"}
                ).encode()
            ),
        )

    service.opener = SimpleNamespace(open=upstream)
    response = service.request("/diagnostics")
    assert response.status_code == 403
    assert json.loads(response.body) == {"detail": "EXTERNAL_LLM_NOT_APPROVED"}
    service.settings.rag_token_file.unlink()
    with pytest.raises(HTTPException) as error:
        service.request("/diagnostics")
    assert (error.value.status_code, error.value.detail) == (503, "RAG_CREDENTIAL_UNAVAILABLE")


@contextmanager
def server(handler):
    instance = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=2)


def test_redirect_does_not_forward_admin_credential(tmp_path, monkeypatch):
    received = []

    class Destination(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    with server(Destination) as destination:

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", f"http://127.0.0.1:{destination.server_port}/target")
                self.end_headers()

            def log_message(self, *args):
                pass

        with server(Redirect) as origin:
            monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{destination.server_port}")
            monkeypatch.setenv("http_proxy", f"http://127.0.0.1:{destination.server_port}")
            monkeypatch.setenv("NO_PROXY", "")
            monkeypatch.setenv("no_proxy", "")
            service = bridge(tmp_path)
            service.settings.rag_base_url = f"http://127.0.0.1:{origin.server_port}"
            with pytest.raises(HTTPException) as error:
                service.request("/diagnostics")
            assert (error.value.status_code, error.value.detail) == (502, "RAG_REDIRECT_DENIED")
    assert received == []
