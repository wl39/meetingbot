from conftest import KEY, FakeModel
from fastapi.testclient import TestClient
from meetingbot_access import COOKIE

from meetingbot_rag.app import create_app


def test_rag_direct_access_obeys_roles_and_revoked_cookie(env):
    settings, _ = env
    app = create_app(settings, FakeModel())
    with TestClient(app) as client:
        visitor = app.state.access.issue_key("visitor", "visitor")
        admin = app.state.access.issue_key("admin", "admin")
        for key, role in ((visitor["key"], "visitor"), (admin["key"], "admin"), (KEY, "superadmin")):
            headers = {"Authorization": "Bearer " + key}
            assert client.get("/api/rag/workspaces", headers=headers).status_code == 200
            assert client.get("/api/rag/llm/settings", headers=headers).status_code == (200 if role == "superadmin" else 403)
            assert client.get("/api/rag/source-roots", headers=headers).status_code == (403 if role == "visitor" else 200)
            assert client.post("/api/rag/uploads", headers=headers, json={}).status_code == 422
            for endpoint in ("/llm/codex/login", "/embedding/install", "/prompts/test"):
                if role != "superadmin":
                    assert client.post("/api/rag" + endpoint, headers=headers, json={}).status_code == 403
        logged_in = client.post("/api/rag/auth/login", json={"key": admin["key"]}).json()
        assert logged_in["role"] == "admin"
        assert client.get("/api/rag/workspaces").status_code == 200
        app.state.access.revoke(admin["id"])
        assert client.get("/api/rag/workspaces").status_code == 401


def test_demo_browser_cookie_cannot_mutate_shared_data_or_read_question_history(env):
    settings, _ = env
    settings.data_dir.mkdir()
    (settings.data_dir / ".demo-instance").touch()
    settings.demo_mode = True
    app = create_app(settings, FakeModel())
    with TestClient(app) as client:
        workspace = app.state.core.workspaces.create("sample", "demo")
        token, principal = app.state.access.issue_session()
        client.cookies.set(COOKIE, token)
        assert client.get("/api/rag/auth/session").json()["role"] == "visitor"
        assert client.get(f"/api/rag/workspaces/{workspace['id']}/questions").json() == []
        headers = {"Origin": "http://127.0.0.1:8766", "X-CSRF-Token": principal.csrf}
        assert client.delete(f"/api/rag/workspaces/{workspace['id']}", headers=headers).status_code == 403
        assert client.post(f"/api/rag/workspaces/{workspace['id']}/search", json={"query": "log"}).status_code == 403
        assert client.get("/api/rag/llm/settings").status_code == 403
        assert client.get("/api/rag/settings").status_code == 403
        assert client.get("/api/rag/workspaces", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_keyless_direct_bootstrap_csrf_roles_and_logout(env):
    settings, _ = env
    app = create_app(settings, FakeModel())
    with TestClient(app) as client:
        assert client.get("/api/rag/workspaces").status_code == 401
        response = client.get("/api/rag/auth/session")
        assert response.status_code == 200
        assert response.json()["role"] == "visitor"
        csrf = response.json()["csrf"]
        cookie = client.cookies.get(COOKIE)
        assert client.get("/api/rag/auth/session").json()["csrf"] == csrf
        assert client.get("/api/rag/workspaces").status_code == 200
        assert client.get("/api/rag/settings").status_code == 403
        assert client.post("/api/rag/auth/logout").status_code == 403
        assert client.get("/api/rag/auth/session", headers={"Authorization": "Bearer wrong"}).status_code == 401
        headers = {"Origin": "http://127.0.0.1:8766", "X-CSRF-Token": csrf}
        assert client.post("/api/rag/auth/logout", headers=headers).status_code == 200
        assert app.state.access.session(cookie, allow_guest=True) is None
        assert not client.cookies.get(COOKIE)


def test_key_only_mode_rejects_keyless_sessions(env):
    settings, _ = env
    settings.keyless_login = False
    app = create_app(settings, FakeModel())
    with TestClient(app) as client:
        cookie, _ = app.state.access.issue_session()
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/rag/auth/session").status_code == 401


def test_rag_audit_includes_background_writes_and_rollback_without_content(env):
    import json

    settings, _ = env
    app = create_app(settings, FakeModel())
    with TestClient(app, headers={"Authorization": "Bearer " + KEY}) as client:
        assert client.get("/api/rag/workspaces?key=PRIVATE_QUERY").status_code == 200
        app.state.core.workspaces.create("PRIVATE_WORKSPACE", "PRIVATE_DESCRIPTION")
        try:
            with app.state.core.db.transaction():
                app.state.core.db.execute("UPDATE workspaces SET deleted=1")
                raise RuntimeError("PRIVATE_ERROR")
        except RuntimeError:
            pass
    raw = (settings.data_dir / "logs/events.jsonl").read_text()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert any(row.get("table") == "workspaces" and row["event"] == "rag.database_write" for row in rows)
    assert any(row.get("outcome") == "rolled_back" for row in rows)
    assert any(row["event"] == "http.completed" and row["status"] == 200 for row in rows)
    for private in (KEY, "PRIVATE_QUERY", "PRIVATE_WORKSPACE", "PRIVATE_DESCRIPTION", "PRIVATE_ERROR"):
        assert private not in raw
