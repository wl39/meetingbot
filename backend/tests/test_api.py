import asyncio
import io
import json
import struct
import subprocess
import time
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.modules.stt.engines.fake import FakeASR, FakeDiarizer
from app.modules.stt.settings import Settings


class FakeWorkers:
    fail_diar = False
    delay = 0

    def __init__(self, settings):
        self.manifest = {}
        self.health = {k: {"ready": True, "mode": "fake"} for k in ("asr", "diar", "vad")}

    async def prepare(self):
        pass

    async def run(self, kind, audio, options, on_progress=None):
        await asyncio.sleep(self.delay)
        if kind == "diar" and self.fail_diar:
            raise RuntimeError("injected failure")
        result = (
            FakeASR().transcribe(audio, options) if kind == "asr" else FakeDiarizer().diarize(audio, options)
        )
        result.diagnostics["inference_seconds"] = 0.01
        return result

    def close(self):
        pass


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings(engine="fake", data_dir=tmp_path, asr_interval=0.01, diar_interval=0.3), FakeWorkers
    )
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        yield client


def wav(seconds=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes((np.sin(np.arange(int(16000 * seconds)) * 0.08) * 8000).astype("<i2").tobytes())
    return buffer.getvalue()


def completed(client, sid):
    for _ in range(200):
        s = client.get("/api/stt/sessions/" + sid).json()
        if s["state"] in ("COMPLETED", "PARTIAL", "FAILED", "INTERRUPTED"):
            return s
        time.sleep(0.02)
    pytest.fail("session did not finish")


def test_auth_origin_and_host(client):
    assert client.get("/api/stt/health", headers={"Authorization": ""}).status_code == 401
    assert (
        client.post("/api/stt/sessions", json={}, headers={"Origin": "https://evil.example"}).status_code
        == 403
    )
    assert client.get("/api/stt/health", headers={"Host": "evil.example"}).status_code == 400


def test_file_transcription_correction_exports_delete(client):
    response = client.post("/api/stt/files", files={"file": ("meeting.wav", wav(), "audio/wav")})
    assert response.status_code == 202
    ids = response.json()
    sid = ids["session_id"]
    s = completed(client, sid)
    assert s["state"] == "COMPLETED"
    assert s["utterances"]
    assert not list(client.app.state.service.settings.data_dir.joinpath("tmp").iterdir())
    u = s["utterances"][0]
    path = f"/api/stt/sessions/{sid}/utterances/{u['utterance_id']}"
    assert client.patch(path, json={"base_revision": u["revision"], "text": "한국어 수정"}).status_code == 200
    assert client.patch(path, json={"base_revision": u["revision"], "text": "충돌"}).status_code == 409
    for fmt in ("json", "txt", "srt"):
        r = client.get(f"/api/stt/sessions/{sid}/export?format={fmt}")
        assert r.status_code == 200 and "한국어 수정" in r.text
    assert client.get(f"/api/stt/sessions/{sid}/audio").status_code == 404
    assert client.delete("/api/stt/sessions/" + sid).status_code == 204
    assert client.get("/api/stt/sessions/" + sid).status_code == 404
    assert client.get("/api/stt/jobs/" + ids["job_id"]).status_code == 404


def test_diar_failure_preserves_text_as_partial(client):
    client.app.state.service.workers.fail_diar = True
    r = client.post("/api/stt/files", files={"file": ("meeting.wav", wav())})
    s = completed(client, r.json()["session_id"])
    assert s["state"] == "PARTIAL"
    assert s["utterances"][0]["speaker_id"] is None
    assert s["utterances"][0]["text"]


def test_invalid_file_cleanup(client):
    r = client.post("/api/stt/files", files={"file": ("bad.wav", b"not audio")})
    s = completed(client, r.json()["session_id"])
    assert s["state"] == "FAILED"
    assert s["warnings"][0]["code"] == "AUDIO_PROBE_FAILED"
    assert s["warnings"][0]["stage"] == "PREPROCESSING"
    assert not list(client.app.state.service.settings.data_dir.joinpath("tmp").iterdir())
    assert client.post("/api/stt/files", files={"file": ("bad.exe", b"data")}).status_code == 415


def test_retention_playback_and_reprocess(client):
    r = client.post(
        "/api/stt/files",
        files={"file": ("meeting.wav", wav())},
        data={"options": json.dumps({"retain_audio": True})},
    )
    s = completed(client, r.json()["session_id"])
    assert s["audio_retained"]
    assert client.get(f"/api/stt/sessions/{s['id']}/audio").content[:4] == b"RIFF"
    r = client.post(f"/api/stt/sessions/{s['id']}/reprocess")
    assert r.status_code == 202
    assert completed(client, r.json()["session_id"])["state"] == "COMPLETED"
    client.delete(f"/api/stt/sessions/{s['id']}")
    assert not client.app.state.service.settings.data_dir.joinpath("audio", s["id"] + ".wav").exists()


def test_cancel_during_inference_does_not_revive_session(client):
    client.app.state.service.workers.delay = 0.2
    r = client.post("/api/stt/files", files={"file": ("meeting.wav", wav())})
    sid = r.json()["session_id"]
    time.sleep(0.1)
    client.delete("/api/stt/sessions/" + sid)
    time.sleep(0.5)
    assert client.get("/api/stt/sessions/" + sid).status_code == 404
    assert client.app.state.service.active is None


def send_pcm(ws, sequence, start, count=2400):
    samples = (np.sin(np.arange(count) * 0.08) * 0.2).astype("<f4")
    ws.send_bytes(struct.pack("<IQI", sequence, start, count) + samples.tobytes())


def connect(client, sid):
    return client.websocket_connect(
        "/api/stt/sessions/" + sid + "/stream",
        headers={"Origin": "http://127.0.0.1:5173"},
        subprotocols=["stt", "stt." + client.app.state.token],
    )


def test_live_final_frame_and_stop_sequence(client):
    sid = client.post("/api/stt/sessions", json={}).json()["id"]
    with connect(client, sid) as ws:
        ws.send_json({"type": "start", "stream_id": "test", "sample_rate": 16000})
        for sequence in range(7):
            send_pcm(ws, sequence, sequence * 2400)
        ws.send_json({"type": "stop", "last_sequence": 100})
        while True:
            message = ws.receive_json()
            if message["type"] == "error":
                assert message["code"] == "STOP_SEQUENCE_MISMATCH"
                break
        ws.send_json({"type": "stop", "last_sequence": 6})
        result = None
        while True:
            message = ws.receive_json()
            if message["type"] == "snapshot":
                result = message["session"]
            if message["type"] == "completed":
                break
        assert result["state"] == "COMPLETED"
        assert result["metrics"]["audio_input_ms"] == 1050
        assert result["utterances"][-1]["end_ms"] == 1050
        assert all(u["status"] == "stable" for u in result["utterances"])


def test_live_disconnect_finalizes_received_audio(client):
    sid = client.post("/api/stt/sessions", json={}).json()["id"]
    with connect(client, sid) as ws:
        ws.send_json({"type": "start", "stream_id": "test", "sample_rate": 16000})
        send_pcm(ws, 0, 0)
        # Wait until the server acknowledges the actual frame before disconnecting.
        while ws.receive_json().get("sequence") != 0:
            pass
    s = completed(client, sid)
    assert s["state"] == "INTERRUPTED"
    assert s["metrics"]["audio_input_ms"] == 150


def test_ws_rejects_foreign_origin(client):
    sid = client.post("/api/stt/sessions", json={}).json()["id"]
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/api/stt/sessions/" + sid + "/stream", headers={"Origin": "https://evil.example"}
        ):
            pass


def test_busy_and_upload_limits(client):
    service = client.app.state.service
    service.workers.delay = 0.2
    r = client.post("/api/stt/files", files={"file": ("x.wav", wav())})
    assert client.post("/api/stt/sessions", json={}).status_code == 409
    completed(client, r.json()["session_id"])
    service.settings.max_file_bytes = 100
    assert client.post("/api/stt/files", files={"file": ("x.wav", wav())}).status_code == 413
    assert service.active is None


def test_duration_limit_and_silence(client):
    client.app.state.service.settings.max_file_seconds = 1
    r = client.post("/api/stt/files", files={"file": ("x.wav", wav(1.5))})
    result = completed(client, r.json()["session_id"])
    assert result["state"] == "FAILED"
    assert result["warnings"][0]["code"] == "AUDIO_TOO_LONG"
    assert result["warnings"][0]["duration_seconds"] == 1.5
    assert result["warnings"][0]["max_seconds"] == 1
    job = client.get("/api/stt/jobs/" + r.json()["job_id"]).json()
    assert job["error"] == "AUDIO_TOO_LONG"
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(16000)
        f.writeframes(bytes(32000))
    r = client.post("/api/stt/files", files={"file": ("silence.wav", buffer.getvalue())})
    assert completed(client, r.json()["session_id"])["utterances"] == []


@pytest.mark.parametrize("codec", ["aac", "alac"])
def test_m4a_stereo_upload(client, tmp_path, codec):
    from app.modules.stt.audio import binary

    source = tmp_path / "source.wav"
    source.write_bytes(wav())
    dest = tmp_path / "recording.m4a"
    subprocess.run(
        [
            binary("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            codec,
            str(dest),
        ],
        check=True,
        capture_output=True,
    )
    response = client.post(
        "/api/stt/files", files={"file": ("recording.m4a", dest.read_bytes(), "audio/mp4")}
    )
    result = completed(client, response.json()["session_id"])
    assert result["state"] == "COMPLETED"
    assert result["metrics"]["source_channels"] == 2
    assert result["metrics"]["downmixed"] is True
    assert result["utterances"]


def test_long_file_chunks_keep_offsets_and_no_overlap_duplicates(client):
    from app.modules.stt.engines.base import ASRResult, DiarizationResult, Turn, Word

    service = client.app.state.service
    service.settings.file_chunk_seconds = 2
    lengths = []

    async def infer(kind, audio, options, on_progress=None):
        duration = len(audio) / 16000
        if kind == "diar":
            assert isinstance(audio, np.memmap)
            return DiarizationResult([Turn(0, duration, "A")], diagnostics={"inference_seconds": 0})
        lengths.append(duration)
        return ASRResult(
            [Word(i + 0.25, min(i + 0.75, duration), " 단어") for i in range(int(np.ceil(duration)))],
            diagnostics={"inference_seconds": 0},
        )

    service.workers.run = infer
    r = client.post("/api/stt/files", files={"file": ("long.wav", wav(7.5))})
    s = completed(client, r.json()["session_id"])
    assert s["state"] == "COMPLETED"
    assert len(lengths) == 4 and max(lengths) <= 6
    assert " ".join(u["text"] for u in s["utterances"]).split() == ["단어"] * 8
    assert s["utterances"][0]["start_ms"] == 250
    assert s["utterances"][-1]["end_ms"] == 7500
    assert s["metrics"]["progress_percent"] == 100
    assert not list(service.settings.data_dir.joinpath("tmp").iterdir())


def test_long_upload_limits_advertised(client):
    limits = client.get("/api/stt/health").json()["limits"]
    assert limits["file_seconds"] == 18000
    assert limits["file_mb"] == 4096
    assert limits["live_seconds"] == 300


def test_300_minute_file_pipeline_and_cleanup(client, tmp_path):
    from app.modules.stt.audio import binary

    fixture = tmp_path / "five-hours.flac"
    subprocess.run(
        [
            binary("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono",
            "-t",
            "18000",
            "-c:a",
            "flac",
            str(fixture),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    r = client.post("/api/stt/files", files={"file": (fixture.name, fixture.read_bytes(), "audio/flac")})
    assert r.status_code == 202
    sid = r.json()["session_id"]
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        session = client.get("/api/stt/sessions/" + sid).json()
        if session["state"] in ("COMPLETED", "PARTIAL", "FAILED"):
            break
        time.sleep(0.1)
    assert session["state"] == "COMPLETED"
    assert session["metrics"]["duration_seconds"] == 18000
    assert session["metrics"]["transcribed_seconds"] == 18000
    assert session["utterances"] == []
    assert not list(client.app.state.service.settings.data_dir.joinpath("tmp").iterdir())


def test_manual_speaker_creation_and_rename(client):
    sid = client.post("/api/stt/sessions", json={}).json()["id"]
    r = client.post(f"/api/stt/sessions/{sid}/speakers", json={"name": "진행자"})
    assert r.status_code == 201
    speaker_id = r.json()["speaker_id"]
    assert (
        client.patch(f"/api/stt/sessions/{sid}/speakers/{speaker_id}", json={"name": "발표자"}).status_code
        == 200
    )
    assert client.get(f"/api/stt/sessions/{sid}").json()["speakers"][speaker_id] == "발표자"


def test_tailnet_https_auth_cors_redirect_and_websocket(tmp_path):
    origin = "https://stt.example.ts.net"
    config = Settings(
        engine="fake",
        data_dir=tmp_path,
        public_origin=origin,
        allowed_hosts=["localhost", "127.0.0.1", "testserver", "stt.example.ts.net", "100.64.0.9"],
        redirect_hosts=["100.64.0.9", "stt.example.ts.net"],
        origins=[origin],
    )
    app = create_app(config, FakeWorkers)
    with TestClient(app, base_url=origin) as c:
        assert c.get("/api/stt/health").status_code == 401
        c.headers["Authorization"] = "Bearer " + app.state.token
        assert c.get("/api/stt/health", headers={"Origin": origin}).status_code == 200
        assert c.get("/api/stt/health", headers={"Origin": "https://other.ts.net"}).status_code == 403
        preflight = c.options(
            "/api/stt/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == origin
        r = c.get("http://100.64.0.9:8765/api/stt/health?x=1", follow_redirects=False)
        assert r.status_code == 307 and r.headers["location"] == origin + "/api/stt/health?x=1"
        assert c.get("http://127.0.0.1:8765/api/stt/health", follow_redirects=False).status_code == 200
        sid = c.post("/api/stt/sessions", json={}).json()["id"]
        with c.websocket_connect(
            f"/api/stt/sessions/{sid}/stream",
            headers={"Origin": origin},
            subprotocols=["stt", "stt." + app.state.token],
        ) as ws:
            ws.send_json({"type": "start", "stream_id": "remote-test", "sample_rate": 48000})
            while True:
                msg = ws.receive_json()
                if msg.get("action") == "start":
                    break
            ws.send_json({"type": "stop", "last_sequence": -1})
            while ws.receive_json()["type"] != "completed":
                pass


@pytest.mark.parametrize(
    "origin",
    [
        "http://stt.example.ts.net",
        "https://stt.example.ts.net/path",
        "https://user:secret@stt.example.ts.net",
        "https://stt.example.ts.net?next=evil",
    ],
)
def test_public_origin_validation(origin):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(public_origin=origin)
