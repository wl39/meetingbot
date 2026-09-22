import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "prepare_models", Path(__file__).resolve().parents[2] / "scripts/prepare_models.py"
)
prepare_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_models)


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare_models, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_models, "load_dotenv", lambda *_: None)
    monkeypatch.setenv("STT_DATA_DIR", "data")
    monkeypatch.setenv("HF_TOKEN", "test-token")
    calls = []

    def download(repo, **kwargs):
        calls.append((repo, kwargs))
        return str(Path(kwargs["cache_dir"]) / repo.replace("/", "--") / "snapshots" / "test-revision")

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    return calls


def test_diarization_only_skips_mlx_and_preserves_installed_asr(tmp_path, downloads):
    directory = tmp_path / "data/models"
    directory.mkdir(parents=True)
    manifest_file = directory / "manifest.json"
    asr = {"repo": "Systran/faster-whisper-small", "path": "/existing/model", "revision": "existing"}
    manifest_file.write_text(json.dumps({"faster-whisper:small": asr}))

    prepare_models.main(["--diarization-only"])

    assert downloads == [
        ("pyannote/speaker-diarization-community-1", {"token": "test-token", "cache_dir": str(directory / "hub")})
    ]
    manifest = json.loads(manifest_file.read_text())
    assert manifest["faster-whisper:small"] == asr
    assert manifest["diarization"]["revision"] == "test-revision"
    assert Path(manifest["diarization"]["path"]).is_relative_to(directory / "hub")
    assert "small" not in manifest


def test_default_install_keeps_mlx_small_behavior(tmp_path, downloads):
    prepare_models.main([])

    assert [repo for repo, _ in downloads] == ["mlx-community/whisper-small-mlx"]
    manifest = json.loads((tmp_path / "data/models/manifest.json").read_text())
    assert set(manifest) == {"small"}


def test_diarization_still_adds_to_selected_mlx_model(downloads):
    prepare_models.main(["--asr", "large-v3-turbo", "--diarization"])

    assert [repo for repo, _ in downloads] == [
        "mlx-community/whisper-large-v3-turbo", "pyannote/speaker-diarization-community-1"
    ]


def test_missing_token_fails_before_downloading_or_writing(tmp_path, downloads, monkeypatch):
    monkeypatch.delenv("HF_TOKEN")

    with pytest.raises(SystemExit) as error:
        prepare_models.main(["--diarization-only"])

    assert error.value.code == 2
    assert not downloads
    assert not (tmp_path / "data").exists()


def test_prompted_token_is_only_passed_to_download(tmp_path, downloads, monkeypatch, capsys):
    monkeypatch.delenv("HF_TOKEN")
    token = "private-prompt-token"
    monkeypatch.setattr(prepare_models.getpass, "getpass", lambda _: token)

    prepare_models.main(["--diarization-only", "--prompt-token"])

    assert downloads[0][1]["token"] == token
    assert "HF_TOKEN" not in os.environ
    output = capsys.readouterr()
    assert token not in output.out + output.err
    assert token not in (tmp_path / "data/models/manifest.json").read_text()
    assert not (tmp_path / ".env").exists()


def test_empty_prompt_fails_before_download(tmp_path, downloads, monkeypatch):
    monkeypatch.setattr(prepare_models.getpass, "getpass", lambda _: "  ")

    with pytest.raises(SystemExit) as error:
        prepare_models.main(["--diarization-only", "--prompt-token"])

    assert error.value.code == 2
    assert not downloads
    assert not (tmp_path / "data").exists()
