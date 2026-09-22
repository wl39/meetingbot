from conftest import KEY, FakeModel
from fastapi.testclient import TestClient
from test_rag import search, wait
from test_uploads import begin, put

from meetingbot_rag.app import create_app


def test_visitor_upload_search_ownership_csrf_and_admin_access(env):
    settings, _ = env
    app = create_app(settings, FakeModel())
    with TestClient(app) as client:
        public = app.state.core.workspaces.create("공용 자료", "")
        guest = client.get("/api/rag/auth/session").json()
        assert begin(client).status_code == 403  # Upload still requires CSRF.
        client.headers.update({"Origin": "http://127.0.0.1:8766", "X-CSRF-Token": guest["csrf"]})
        assert client.get("/api/rag/uploads/limits").status_code == 200
        row = begin(client).json()
        first_cookie = dict(client.cookies)
        assert put(client, row).status_code == 200
        result = client.post(f"/api/rag/uploads/{row['id']}/commit", json={}).json()
        wid = result["workspace"]["id"]
        assert result["workspace"]["visibility"] == "private"
        assert result["workspace"]["can_manage"]
        assert wait(client, wid, result["job"]["job_id"])["state"] == "READY"
        assert "75일" in search(client, wid)["evidence"][0]["text"]
        assert client.patch(f"/api/rag/workspaces/{wid}", json={"name": "내 자료"}).status_code == 200
        assert client.get(f"/api/rag/workspaces/{wid}/guide").status_code == 200
        assert client.post(f"/api/rag/workspaces/{wid}/sources", json={}).status_code == 403
        assert client.delete(f"/api/rag/workspaces/{public['id']}").status_code == 403
        client.cookies.clear()
        other = client.get("/api/rag/auth/session").json()
        client.headers["X-CSRF-Token"] = other["csrf"]
        assert wid not in [w["id"] for w in client.get("/api/rag/workspaces").json()]
        assert public["id"] in [w["id"] for w in client.get("/api/rag/workspaces").json()]
        for method, path in (("GET", f"/uploads/{row['id']}"), ("DELETE", f"/uploads/{row['id']}"),
                             ("POST", f"/uploads/{row['id']}/commit"),
                             ("PUT", f"/uploads/{row['id']}/files/{row['files'][0]['id']}"),
                             ("GET", f"/workspaces/{wid}"), ("GET", f"/workspaces/{wid}/documents"),
                             ("GET", f"/workspaces/{wid}/questions"), ("POST", f"/workspaces/{wid}/search"),
                             ("DELETE", f"/workspaces/{wid}"), ("PATCH", f"/workspaces/{wid}")):
            assert client.request(method, "/api/rag" + path).status_code == 404, path
        admin = app.state.access.issue_key("자료 관리자", "admin")
        assert client.get(f"/api/rag/workspaces/{wid}", headers={"Authorization": "Bearer " + admin["key"]}).status_code == 200
        assert client.get(f"/api/rag/workspaces/{wid}", headers={"Authorization": "Bearer " + KEY}).status_code == 200
        client.cookies.clear()
        client.cookies.update(first_cookie)
        client.headers["X-CSRF-Token"] = guest["csrf"]
        assert client.delete(f"/api/rag/workspaces/{wid}").status_code == 200
        assert not app.state.core.db.one("SELECT * FROM upload_sessions WHERE id=?", (row["id"],))
