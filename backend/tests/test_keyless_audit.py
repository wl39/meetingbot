import json
import os
import stat

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from meetingbot_access.audit import AuditLog, AuditMiddleware
from starlette.websockets import WebSocketDisconnect
from test_api import FakeWorkers, completed, wav

from app.main import create_app
from app.modules.stt.settings import Settings

ORIGIN = "http://127.0.0.1:8765"


def rows(directory):
    return [json.loads(line) for line in (directory / "logs/events.jsonl").read_text().splitlines()]


def test_keyless_normal_session_upload_and_isolation(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        info = client.get("/api/access/session")
        assert info.json()["keyless"] and not info.json()["demo"]
        assert info.json()["role"] == "visitor"
        assert info.json()["limits"]["seconds"] == 18000
        assert "HttpOnly" in info.headers["set-cookie"]
        csrf = info.json()["csrf"]
        assert client.get("/api/access/session").json()["csrf"] == csrf
        assert client.get("/api/system").status_code == 403
        assert client.post("/api/stt/sessions", json={}).status_code == 403
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
        response = client.post("/api/stt/files", files={"file": ("private-name.wav", wav(), "audio/wav")})
        assert response.status_code == 202
        sid = response.json()["session_id"]
        assert completed(client, sid)["state"] == "COMPLETED"
        rid = response.headers["x-request-id"]
        assert any(
            r["event"] == "stt.job_updated" and r["state"] == "COMPLETED" and r["request_id"] == rid
            for r in rows(tmp_path)
        )
        assert client.get(f"/api/stt/sessions/{sid}/export").status_code == 200
        first_cookie = client.cookies.get("meetingbot_session")
        assert client.post("/api/access/logout").status_code == 200
        assert app.state.access.session(first_cookie, allow_guest=True) is None
        client.get("/api/access/session")
        assert client.get(f"/api/stt/sessions/{sid}").status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/api/stt/sessions/{sid}/stream", headers={"Origin": ORIGIN}):
                pass
        assert (
            client.get("/api/access/session", headers={"Authorization": "Bearer wrong"}).json()[
                "authenticated"
            ]
            is False
        )
        raw = (tmp_path / "logs/events.jsonl").read_text()
        assert "private-name" not in raw and first_cookie not in raw and csrf not in raw
    events = {r["event"] for r in rows(tmp_path)}
    assert {
        "auth.session_created",
        "auth.logout",
        "stt.utterance",
        "websocket.completed",
        "service.stopped",
    } <= events


def test_audit_covers_denials_browser_validation_and_redaction(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        assert client.post("/api/events", json={"events": []}).status_code == 401
        response = client.get("/api/access/session?token=QUERY_SECRET")
        csrf = response.json()["csrf"]
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": csrf})
        event = {"action": "click", "page": "/", "target": "body:1/button:3"}
        assert client.post("/api/events", json={"events": [event]}).status_code == 202
        assert (
            client.post("/api/events", json={"events": [{**event, "value": "BODY_SECRET"}]}).status_code
            == 422
        )
        assert client.post("/api/events", json={"events": [event] * 51}).status_code == 422
        assert client.get("/api/system", headers={"Authorization": "Bearer AUTH_SECRET"}).status_code == 401
        assert client.get("/api/stt/health", headers={"Host": "evil.example"}).status_code == 400
        assert client.get("/api/stt/health", headers={"Origin": "https://evil.example"}).status_code == 403
    data = rows(tmp_path)
    assert {200, 202, 400, 401, 403, 422} <= {r.get("status") for r in data}
    assert any(r.get("route") == "/api/system" and r.get("status") == 401 for r in data)
    assert any(r["event"] == "browser.click" and r["role"] == "visitor" for r in data)
    raw = (tmp_path / "logs/events.jsonl").read_text()
    for secret in ("QUERY_SECRET", "BODY_SECRET", "AUTH_SECRET", csrf):
        assert secret not in raw


def test_audit_exception_and_rotation(tmp_path):
    audit = AuditLog(tmp_path, "test", max_bytes=1200, backups=2)
    app = FastAPI()
    app.add_middleware(AuditMiddleware, audit=audit, application=app)

    @app.get("/fail")
    def fail():
        raise ValueError("PRIVATE_EXCEPTION")

    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/fail").status_code == 500
    data = [json.loads(line) for line in audit.path.read_text().splitlines()]
    assert any(r.get("status") == 500 and r.get("error_type") == "ValueError" for r in data)
    assert "PRIVATE_EXCEPTION" not in audit.path.read_text()
    for _ in range(100):
        audit.emit("test.event", token="SECRET", text="PRIVATE_TEXT")
    audit.close()
    files = list(tmp_path.glob("events.jsonl*"))
    assert len(files) == 3
    for path in files:
        if os.name != "nt":  # chmod does not express Windows ACLs.
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_size <= 1200
        assert "SECRET" not in path.read_text() and "PRIVATE_TEXT" not in path.read_text()
        for line in path.read_text().splitlines():
            json.loads(line)


def test_keyless_live_stream_records_frames_without_audio(tmp_path):
    from test_api import send_pcm

    app = create_app(
        Settings(_env_file=None, data_dir=tmp_path, engine="fake", asr_interval=0.01, diar_interval=0.3),
        FakeWorkers,
    )
    with TestClient(app) as client:
        access = client.get("/api/access/session").json()
        client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": access["csrf"]})
        sid = client.post("/api/stt/sessions", json={}).json()["id"]
        with client.websocket_connect(
            f"/api/stt/sessions/{sid}/stream", subprotocols=["stt"], headers={"Origin": ORIGIN}
        ) as ws:
            ws.send_json({"type": "start", "stream_id": "PRIVATE_STREAM_ID", "sample_rate": 16000})
            send_pcm(ws, 0, 0)
            ws.send_json({"type": "stop", "last_sequence": 0})
            while ws.receive_json()["type"] != "completed":
                pass
        assert completed(client, sid)["state"] == "COMPLETED"
    data = rows(tmp_path)
    assert any(r["event"] == "websocket.received" and r.get("bytes", 0) > 1000 for r in data)
    assert any(r["event"] == "websocket.completed" and r["role"] == "visitor" for r in data)
    assert "PRIVATE_STREAM_ID" not in (tmp_path / "logs/events.jsonl").read_text()
