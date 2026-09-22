import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_api import FakeWorkers

from app.main import create_app
from app.modules.stt.settings import Settings

ORIGIN = "http://127.0.0.1:8765"


@pytest.fixture
def demo(tmp_path):
    (tmp_path / ".demo-instance").touch()
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, demo_mode=True, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        yield client


def guest(client):
    client.cookies.clear()
    value = client.get("/api/access/session").json()
    assert value["authenticated"] and value["role"] == "visitor" and value["demo"]
    client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": value["csrf"]})
    return value


def test_demo_does_not_disable_auth_or_csrf(demo):
    assert demo.get("/api/stt/health").status_code == 401
    guest(demo)
    assert demo.get("/api/stt/health").status_code == 200
    assert demo.post("/api/stt/sessions", json={}, headers={"X-CSRF-Token": ""}).status_code == 403
    assert demo.post("/api/stt/sessions", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert demo.get("/api/stt/health", headers={"Authorization": "Bearer invalid"}).status_code == 401
    info = demo.get("/api/access/session").json()
    assert info["limits"]["seconds"] == 180 and info["limits"]["file_mb"] == 20
    assert demo.post("/api/stt/files/stream", json={"filename": "large.wav", "size": 21 * 1024 * 1024, "options": {}}).status_code == 413
    assert "HttpOnly" in demo.get("/api/access/session").headers.get("set-cookie", "") or demo.cookies


def test_visitors_cannot_access_each_others_records_or_websockets(demo):
    guest(demo)
    session = demo.post("/api/stt/sessions", json={"retain_audio": True}).json()
    sid = session["id"]
    assert session["options"]["retain_audio"] is False
    demo.app.state.service.repo.job("testjob", sid, "QUEUED")
    assert len(demo.get("/api/stt/sessions").json()) == 1
    guest(demo)
    assert demo.get("/api/stt/sessions").json() == []
    for suffix in ("", "/events", "/export", "/export/preview", "/audio"):
        assert demo.get(f"/api/stt/sessions/{sid}" + suffix).status_code == 404
    assert demo.get("/api/stt/jobs/testjob").status_code == 404
    assert demo.delete(f"/api/stt/sessions/{sid}").status_code == 404
    assert demo.patch(f"/api/stt/sessions/{sid}/speakers/spk", json={"name": "x"}).status_code == 404
    assert demo.put(f"/api/stt/files/{sid}/chunks/0", content=b"x").status_code == 404
    assert demo.post(f"/api/stt/files/{sid}/finish").status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with demo.websocket_connect(f"/api/stt/sessions/{sid}/stream", subprotocols=["stt"], headers={"Origin": ORIGIN}):
            pass


def test_three_roles_and_key_revocation(demo):
    store = demo.app.state.access
    visitor = store.issue_key("visitor", "visitor")
    admin = store.issue_key("admin", "admin")
    superkey = demo.app.state.token
    for key, role in ((visitor["key"], "visitor"), (admin["key"], "admin"), (superkey, "superadmin")):
        headers = {"Authorization": "Bearer " + key}
        assert demo.get("/api/access/session", headers=headers).json()["role"] == role
        expected = 200 if role == "superadmin" else 403
        assert demo.get("/api/access/keys", headers=headers).status_code == expected
        assert demo.get("/api/system", headers=headers).status_code == expected
        assert demo.post("/api/access/keys", headers=headers, json={"role": "admin", "label": "x"}).status_code == (201 if role == "superadmin" else 403)
    token, principal = store.issue_session(store.key(admin["key"]))
    store.revoke(admin["id"])
    assert store.session(token) is None
    assert store.key(admin["key"]) is None
    assert demo.get("/api/access/keys", headers={"Authorization": "Bearer " + superkey}).json()["keys"]
    assert all("hash" not in row and "key" not in row for row in store.keys())


def test_daily_limit_cannot_be_reset_by_new_anonymous_cookie(demo):
    demo.app.state.service.settings.demo_daily_jobs = 2
    for _ in range(2):
        guest(demo)
        assert demo.post("/api/stt/sessions", json={}).status_code == 201
    guest(demo)
    assert demo.post("/api/stt/sessions", json={}).status_code == 429


def test_demo_requires_separate_explicit_data_directory(tmp_path):
    with pytest.raises(ValueError, match="isolated"):
        create_app(Settings(_env_file=None, data_dir=tmp_path, demo_mode=True, engine="fake"), FakeWorkers)
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake", keyless_login=False), FakeWorkers)
    with TestClient(app) as client:
        assert client.get("/api/access/session").json()["authenticated"] is False
        assert client.get("/api/stt/sessions").status_code == 401


def test_public_demo_uses_secure_cookie_and_owned_websocket(tmp_path):
    (tmp_path / ".demo-instance").touch()
    origin = "https://demo.example"
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, demo_mode=True, engine="fake",
                             public_origin=origin, allowed_hosts=["demo.example"], origins=[origin]), FakeWorkers)
    with TestClient(app, base_url=origin) as client:
        response = client.get("/api/access/session")
        assert "Secure" in response.headers["set-cookie"]
        assert "HttpOnly" in response.headers["set-cookie"]
        client.headers.update({"Origin": origin, "X-CSRF-Token": response.json()["csrf"]})
        sid = client.post("/api/stt/sessions", json={}).json()["id"]
        with client.websocket_connect(f"wss://demo.example/api/stt/sessions/{sid}/stream", subprotocols=["stt"], headers={"Origin": origin}):
            pass
