import asyncio
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers

from app.main import create_app
from app.modules.stt.settings import Settings
from app.modules.system import catalog
from app.modules.system.catalog import write_json


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.modules.system.manager.supported", lambda _: True)
    monkeypatch.setattr("app.modules.system.manager.engine_installed", lambda *_: True)
    app = create_app(Settings(engine="fake", data_dir=tmp_path), FakeWorkers)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        yield client


def installed(client, engine="faster-whisper", model="small"):
    directory = client.app.state.service.settings.data_dir
    snapshot = directory / "models" / "snapshot"
    snapshot.mkdir(parents=True, exist_ok=True)
    write_json(directory / "models" / "manifest.json", {engine + ":" + model: {
        "path": str(snapshot), "repo": "test", "revision": "test-commit",
    }})


def finish(client, identifier):
    for _ in range(200):
        job = client.get("/api/system/jobs/" + identifier).json()
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.01)
    pytest.fail("job did not complete")


def test_auth_catalog_and_allowlist(client):
    assert client.get("/api/system", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/system/install", json={"engine": "faster-whisper", "model": "small"},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    status = client.get("/api/system").json()
    assert len(status["models"]) == 4
    assert status["updates"]["supported"] is False
    assert status["storage"]["free_bytes"] > 0
    for body in ({"engine": "custom", "model": "small"},
                 {"engine": "faster-whisper", "model": "../../tmp"},
                 {"engine": "faster-whisper", "model": "small", "url": "https://evil.example"}):
        assert client.post("/api/system/install", json=body).status_code == 422


@pytest.mark.parametrize("public_origin, kind", [
    (None, None),
    ("https://meeting.example-tailnet.ts.net", "tailscale"),
    ("https://meetings.example.com", "custom"),
    ("https://meeting.ts.net.example.com", "custom"),
])
def test_access_uses_configured_endpoint_not_forwarded_headers(client, public_origin, kind):
    client.app.state.service.settings.public_origin = public_origin
    response = client.get("/api/system", headers={
        "X-Forwarded-Host": "attacker.example.com",
        "Forwarded": "host=attacker.example.com;proto=https",
    })
    assert response.status_code == 200
    assert response.json()["access"] == {
        "local_url": "http://127.0.0.1:8765",
        "remote_url": public_origin,
        "kind": kind,
    }


def test_activation_applies_persists_and_default_options(client):
    installed(client, model="large-v3-turbo")
    response = client.post("/api/system/selection", json={"engine": "faster-whisper", "model": "large-v3-turbo"})
    assert response.status_code == 202
    assert finish(client, response.json()["id"])["status"] == "completed"
    settings = client.app.state.service.settings
    assert settings.asr_backend == "faster-whisper"
    assert settings.default_model == "large-v3-turbo"
    assert json.loads((settings.data_dir / "system-selection.json").read_text())["model"] == "large-v3-turbo"
    assert client.post("/api/stt/sessions", json={}).json()["options"]["model"] == "large-v3-turbo"
    restored = Settings(engine="fake", data_dir=settings.data_dir)
    catalog.load_selection(restored)
    assert restored.asr_backend == "faster-whisper" and restored.default_model == "large-v3-turbo"


def test_selection_rejects_active_and_uninstalled(client):
    body = {"engine": "faster-whisper", "model": "small"}
    assert client.post("/api/system/selection", json=body).status_code == 409
    installed(client)
    client.app.state.service.active = "session_busy"
    assert client.post("/api/system/selection", json=body).json()["detail"] == "TRANSCRIPTION_ACTIVE"


def test_failed_activation_keeps_working_engine(client):
    installed(client)
    old = client.app.state.service.workers

    class FailedWorkers(FakeWorkers):
        def __init__(self, settings):
            super().__init__(settings)
            self.health["asr"] = {"ready": False}

    client.app.state.runtime.worker_factory = FailedWorkers
    response = client.post("/api/system/selection", json={"engine": "faster-whisper", "model": "small"})
    job = finish(client, response.json()["id"])
    assert job["error"] == "MODEL_LOAD_FAILED"
    assert client.app.state.service.workers is old
    assert not (client.app.state.service.settings.data_dir / "system-selection.json").exists()
    assert not client.app.state.service.management_busy


def test_swap_blocks_transcription_and_parallel_jobs(client):
    installed(client)

    class SlowWorkers(FakeWorkers):
        async def prepare(self):
            await asyncio.sleep(0.25)

    client.app.state.runtime.worker_factory = SlowWorkers
    body = {"engine": "faster-whisper", "model": "small"}
    response = client.post("/api/system/selection", json=body)
    assert client.post("/api/stt/sessions", json={}).json()["detail"] == "MANAGEMENT_BUSY"
    assert client.post("/api/system/install", json=body).status_code == 409
    assert finish(client, response.json()["id"])["status"] == "completed"


def test_install_uses_isolated_environment_and_records_exact_snapshot(client, monkeypatch):
    runtime = client.app.state.runtime
    monkeypatch.setattr(runtime, "uv", lambda: "/test/uv")
    calls = []

    async def command(args, code, timeout=7200):
        calls.append([str(arg) for arg in args])
        if str(args[1]).endswith("download.py"):
            snapshot = runtime.directory / "models" / "fixed-commit"
            snapshot.mkdir(parents=True)
            write_json(Path(args[-1]), {"path": str(snapshot), "revision": "fixed-commit", "repo": args[2]})

    monkeypatch.setattr(runtime, "command", command)
    response = client.post("/api/system/install", json={"engine": "faster-whisper", "model": "small"})
    assert response.status_code == 202
    assert finish(client, response.json()["id"])["status"] == "completed"
    assert calls[0][1] == "venv"
    assert str(runtime.directory / "engines" / "faster-whisper") in calls[0]
    assert "faster-whisper>=1.2,<2" in calls[1]
    assert calls[-1][2] == "Systran/faster-whisper-small"
    assert catalog.installed_models(runtime.directory)["faster-whisper:small"]["revision"] == "fixed-commit"
    assert runtime.service.settings.asr_backend == "auto"  # installation is separate from activation


def test_interrupted_jobs_are_terminal_on_startup(tmp_path):
    write_json(tmp_path / "system-jobs.json", [{"id": "old", "status": "running"}])
    app = create_app(Settings(engine="fake", data_dir=tmp_path), FakeWorkers)
    with TestClient(app):
        assert app.state.runtime.jobs[0]["status"] == "failed"
        assert app.state.runtime.jobs[0]["error"] == "INTERRUPTED"


def test_legacy_mlx_manifest_remains_usable(tmp_path):
    snapshot = tmp_path / "model"
    snapshot.mkdir()
    write_json(tmp_path / "models" / "manifest.json", {"small": {"path": str(snapshot), "revision": "original"}})
    settings = Settings(data_dir=tmp_path, asr_backend="mlx")
    assert catalog.worker_manifest(settings)["small"]["revision"] == "original"
    assert catalog.model_installed(tmp_path, "mlx", "small")


def test_faster_whisper_adapter_is_offline_cpu_and_preserves_words(monkeypatch):
    from app.modules.stt.engines.faster_whisper_engine import FasterWhisperEngine

    captured = {}

    class Model:
        def __init__(self, path, **kwargs):
            captured.update(path=path, **kwargs)

        def transcribe(self, audio, **kwargs):
            captured.update(kwargs)
            word = SimpleNamespace(start=0.1, end=0.7, word=" 안녕하세요")
            return iter([SimpleNamespace(text="안녕하세요", words=[word])]), SimpleNamespace(language="ko")

    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Model))
    result = FasterWhisperEngine("/local/model").transcribe(np.zeros(16000), {"language": "ko"})
    assert captured["device"] == "cpu" and captured["compute_type"] == "int8"
    assert captured["local_files_only"] is True and captured["word_timestamps"] is True
    assert result.words[0].text == " 안녕하세요" and result.words[0].start == 0.1


def test_isolated_engine_subprocess_protocol_and_cleanup(tmp_path, monkeypatch):
    from app.modules.stt.engines.external import ExternalASR

    # This fixture shadows only the external engine package in a child process.
    # Exercise the real runner and IPC without downloading or loading a model.
    (tmp_path / "faster_whisper.py").write_text(
        "from types import SimpleNamespace\n"
        "class WhisperModel:\n"
        "    def __init__(self, path, **kwargs):\n"
        "        assert kwargs['local_files_only'] and kwargs['device'] == 'cpu'\n"
        "    def transcribe(self, audio, **kwargs):\n"
        "        assert len(audio) == 16000 and kwargs['word_timestamps']\n"
        "        word = SimpleNamespace(start=0.1, end=0.7, word=' 테스트')\n"
        "        return iter([SimpleNamespace(text='테스트', words=[word])]), SimpleNamespace(language='ko')\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    engine = ExternalASR(sys.executable, "faster-whisper", str(tmp_path))
    try:
        result = engine.transcribe(np.zeros(16000), {"language": "ko"})
        assert result.language == "ko" and result.words[0].text == " 테스트"
        assert result.words[0].start == 0.1
    finally:
        engine.close()
    assert engine.process.poll() is not None


@pytest.mark.parametrize("system,machine,expected", [("Windows", "AMD64", True), ("Windows", "ARM64", False),
                                                   ("Linux", "x86_64", True), ("Darwin", "arm64", True)])
def test_engine_platform_support(monkeypatch, system, machine, expected):
    monkeypatch.setattr(catalog.platform, "system", lambda: system)
    monkeypatch.setattr(catalog.platform, "machine", lambda: machine)
    assert catalog.supported("faster-whisper") is expected
    assert catalog.supported("mlx") is (system == "Darwin" and machine == "arm64")
