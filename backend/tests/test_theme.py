from fastapi.testclient import TestClient
from meetingbot_access import AccessStore
from test_api import FakeWorkers

from app.main import create_app
from app.modules.stt.settings import Settings


def test_theme_public_read_admin_write_validation_and_persistence(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        assert client.get("/api/system/theme").json() == {"color": "#b85c12"}
        guest = client.get("/api/access/session").json()
        assert client.post("/api/system/theme", json={"color": "#112233"}, headers={
            "Origin": "http://127.0.0.1:8765", "X-CSRF-Token": guest["csrf"]}).status_code == 403
        token, principal = app.state.access.issue_session(app.state.access.key(app.state.token))
        client.cookies.set("meetingbot_session", token)
        assert client.post("/api/system/theme", json={"color": "#112233"}).status_code == 403
        headers = {"Authorization": "Bearer " + app.state.token}
        assert client.post("/api/system/theme", json={"color": "red; color:black"}, headers=headers).status_code == 422
        assert client.post("/api/system/theme", json={"color": "#A65C24"}, headers=headers).json() == {"color": "#a65c24"}
        client.cookies.clear()
        assert client.get("/api/system/theme").json() == {"color": "#a65c24"}
        reopened = AccessStore(tmp_path / "local-token")
        assert reopened.theme() == {"color": "#a65c24"}
