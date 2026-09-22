import subprocess
import time

import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers, completed, wav

from app.main import create_app
from app.modules.stt.settings import Settings
from app.modules.stt.upload_stream import StreamingUpload


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(engine="fake", data_dir=tmp_path), FakeWorkers)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        try:
            yield client
        finally:
            for sid in list(app.state.service.uploads):
                client.delete(f"/api/stt/sessions/{sid}")


def begin(client, body, name="stream.wav"):
    r = client.post("/api/stt/files/stream", json={"filename": name, "size": len(body), "options": {}})
    assert r.status_code == 201
    return r.json()


def put(client, ids, body, index):
    size = ids["chunk_bytes"]
    return client.put(
        f"/api/stt/files/{ids['session_id']}/chunks/{index}",
        content=body[index * size : (index + 1) * size],
        headers={"Content-Type": "application/octet-stream"},
    )


def test_analysis_starts_before_upload_finishes(client, monkeypatch):
    monkeypatch.setattr(StreamingUpload, "chunk_bytes", 65536)
    body = wav(60)
    ids = begin(client, body)
    sid = ids["session_id"]
    count = (len(body) + ids["chunk_bytes"] - 1) // ids["chunk_bytes"]
    sent = {0, count - 1, *range(1, 12)}
    for index in sorted(sent):
        assert put(client, ids, body, index).status_code == 200
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        session = client.get(f"/api/stt/sessions/{sid}").json()
        if session["utterances"] or session["state"] == "FAILED":
            break
        time.sleep(0.1)
    assert session["utterances"], session["warnings"]
    assert session["metrics"]["upload_percent"] < 100
    assert session["state"] == "TRANSCRIBING"
    for index in range(count):
        if index not in sent:
            assert put(client, ids, body, index).status_code == 200
    assert client.post(f"/api/stt/files/{sid}/finish").status_code == 202
    result = completed(client, sid)
    assert result["state"] == "COMPLETED", result["warnings"]
    assert result["metrics"]["duration_seconds"] == 60
    assert not list(client.app.state.service.settings.data_dir.joinpath("tmp").iterdir())


def test_stream_validation_and_cancel(client, monkeypatch):
    monkeypatch.setattr(StreamingUpload, "chunk_bytes", 65536)
    body = wav(5)
    ids = begin(client, body)
    sid = ids["session_id"]
    assert client.post(f"/api/stt/files/{sid}/finish").status_code == 409
    assert put(client, ids, body, 0).status_code == 200
    assert put(client, ids, body, 0).status_code == 409
    assert put(client, ids, body, 1000).status_code == 409
    assert client.delete(f"/api/stt/sessions/{sid}").status_code == 204
    deadline = time.monotonic() + 5
    while client.app.state.service.active and time.monotonic() < deadline:
        time.sleep(0.05)
    assert client.app.state.service.active is None
    assert not list(client.app.state.service.settings.data_dir.joinpath("tmp").iterdir())


def test_stream_limits_and_auth(client):
    assert (
        client.post(
            "/api/stt/files/stream", json={"filename": "a.wav", "size": 5}, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert client.post("/api/stt/files/stream", json={"filename": "a.txt", "size": 5}).status_code == 415
    assert (
        client.post("/api/stt/files/stream", json={"filename": "a.wav", "size": 4294967297}).status_code
        == 413
    )


def test_m4a_end_metadata_streaming(client, monkeypatch, tmp_path):
    from app.modules.stt.audio import binary

    monkeypatch.setattr(StreamingUpload, "chunk_bytes", 8192)
    monkeypatch.setattr(StreamingUpload, "idle_seconds", 12)
    source = tmp_path / "speech.wav"
    source.write_bytes(wav(60))
    dest = tmp_path / "speech.m4a"
    subprocess.run(
        [binary("ffmpeg"), "-nostdin", "-v", "error", "-i", str(source), "-c:a", "aac", str(dest)],
        check=True,
        capture_output=True,
    )
    body = dest.read_bytes()
    ids = begin(client, body, dest.name)
    size = ids["chunk_bytes"]
    count = (len(body) + size - 1) // size
    offset = 0
    metadata = {0, count - 1}
    while offset + 8 <= len(body):
        length = int.from_bytes(body[offset : offset + 4], "big")
        if body[offset + 4 : offset + 8] == b"moov":
            assert offset > len(body) // 2
            metadata.update(range(offset // size, (offset + length - 1) // size + 1))
            break
        if length < 8:
            break
        offset += length
    sent = metadata | set(range(count // 2))
    for index in [*metadata, *sorted(sent - metadata)]:
        assert put(client, ids, body, index).status_code == 200
    sid = ids["session_id"]
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        s = client.get(f"/api/stt/sessions/{sid}").json()
        if s["utterances"] or s["state"] == "FAILED":
            break
        time.sleep(0.1)
    assert s["utterances"], s["warnings"]
    assert s["metrics"]["upload_percent"] < 100
    for index in range(count):
        if index not in sent:
            assert put(client, ids, body, index).status_code == 200
    assert client.post(f"/api/stt/files/{sid}/finish").status_code == 202
    assert completed(client, sid)["state"] == "COMPLETED"


def test_rename_updates_all_utterances_and_exports(client):
    from app.modules.stt.engines.base import Turn, Word
    from app.modules.stt.transcript_assembler import assemble

    repo = client.app.state.service.repo
    s = repo.create("file", {"model": "small"}, {})
    sid = s["id"]
    client.app.state.access.owner(sid, "superadmin")
    words = [Word(0, 1, "첫 발언"), Word(15, 16, "다른 발언"), Word(30, 31, "다음 발언")]
    events = assemble(sid, "file", words, [Turn(0, 1, "A"), Turn(15, 16, "B"), Turn(30, 31, "A")], final=True)
    repo.publish(sid, 1, events)
    assert client.patch(f"/api/stt/sessions/{sid}/speakers/A", json={"name": "임완규"}).status_code == 200
    repo.publish(sid, 1, events)
    result = client.get(f"/api/stt/sessions/{sid}").json()
    assert [result["speakers"][u["speaker_id"]] for u in result["utterances"]] == [
        "임완규",
        "화자 B",
        "임완규",
    ]
    assert client.get(f"/api/stt/sessions/{sid}/export?format=txt").text.count("임완규") == 2
    assert client.patch(f"/api/stt/sessions/{sid}/speakers/A", json={"name": "   "}).status_code == 422
