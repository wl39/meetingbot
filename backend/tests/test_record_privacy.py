"""Audio and transcripts remain private even when a caller manages shared documents."""

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_api import FakeWorkers, completed, wav

from app.main import create_app
from app.modules.stt.settings import Settings

ORIGIN = "http://127.0.0.1:8765"


@pytest.mark.parametrize("role", ["visitor", "admin", "superadmin", "installation"])
@pytest.mark.parametrize("mode", ["microphone", "file"])
def test_every_role_can_only_list_read_modify_or_delete_its_own_audio(tmp_path, role, mode):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        owner = app.state.access.issue_key("record owner", "visitor")
        owner_headers = {"Authorization": "Bearer " + owner["key"]}
        other_key = (
            app.state.token if role == "installation"
            else app.state.access.issue_key("different account", role)["key"]
        )
        other_headers = {"Authorization": "Bearer " + other_key}
        client.headers.update(owner_headers)
        if mode == "microphone":
            record = client.post("/api/stt/sessions", json={}).json()
        else:
            response = client.post("/api/stt/files", files={"file": ("private.wav", wav(), "audio/wav")})
            assert response.status_code == 202
            record = completed(client, response.json()["session_id"])
        sid = record["id"]
        record["audio_retained"] = True
        app.state.service.repo.save(record)
        audio = tmp_path / "audio" / f"{sid}.wav"
        audio.write_bytes(wav())
        app.state.service.repo.job("private-job", sid, "COMPLETED")
        assert client.get(f"/api/stt/sessions/{sid}/audio").status_code == 200
        assert [item["id"] for item in client.get("/api/stt/sessions").json()] == [sid]

        client.headers.update(other_headers)
        assert client.get("/api/stt/sessions").json() == []
        for suffix in ("", "/events", "/export", "/export/preview", "/audio"):
            assert client.get(f"/api/stt/sessions/{sid}{suffix}").status_code == 404
        assert client.get("/api/stt/jobs/private-job").status_code == 404
        assert client.delete(f"/api/stt/sessions/{sid}").status_code == 404
        assert client.post(f"/api/stt/sessions/{sid}/reprocess").status_code == 404
        assert client.post(f"/api/stt/sessions/{sid}/speakers", json={"name": "other"}).status_code == 404
        assert client.patch(f"/api/stt/sessions/{sid}/utterances/any", json={"base_revision": 1, "text": "other"}).status_code == 404
        assert client.put(f"/api/stt/files/{sid}/chunks/0", content=b"other").status_code == 404
        assert client.post(f"/api/stt/files/{sid}/finish").status_code == 404
        assert client.get(f"/api/stt/meeting/sessions/{sid}/subscription").status_code == 404
        assert client.get(f"/api/stt/meeting/sessions/{sid}/jobs", params={"workspace_id": "a" * 32}).status_code == 404
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/api/stt/sessions/{sid}/stream",
                subprotocols=["stt", "stt." + other_key],
                headers={"Origin": ORIGIN},
            ):
                pass
        app.state.service.active = sid
        assert client.get("/api/stt/health").json()["active_session"] == "busy"
        app.state.service.active = None
        # Denied operations must leave the owner's data intact.
        client.headers.update(owner_headers)
        assert client.get(f"/api/stt/sessions/{sid}").status_code == 200
        assert client.delete(f"/api/stt/sessions/{sid}").status_code == 204
        assert not audio.exists()
        assert client.get("/api/stt/sessions").json() == []
        assert client.get(f"/api/stt/sessions/{sid}/export").status_code == 404
        assert client.get("/api/stt/jobs/private-job").status_code == 404


def test_ownerless_legacy_records_are_not_assigned_to_any_caller(tmp_path):
    app = create_app(Settings(_env_file=None, data_dir=tmp_path, engine="fake"), FakeWorkers)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        orphan = app.state.service.repo.create("microphone", {}, {})
        assert client.get("/api/stt/sessions").json() == []
        assert client.get(f"/api/stt/sessions/{orphan['id']}").status_code == 404
        assert client.delete(f"/api/stt/sessions/{orphan['id']}").status_code == 404
        assert app.state.service.repo.get(orphan["id"])
