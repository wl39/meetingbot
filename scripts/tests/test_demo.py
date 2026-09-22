import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("meetingbot_demo", Path(__file__).parents[1] / "demo.py")
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


def test_preparation_keeps_secrets_and_data_separate(tmp_path, monkeypatch):
    monkeypatch.setenv("RAG_CLIPROXY_API_KEY", "do-not-copy-this-secret")
    monkeypatch.setenv("RAG_EXTERNAL_LLM_ALLOWED", "true")
    state = tmp_path / "demo"
    env = demo.prepare(state, 8985, 8986)
    assert "RAG_CLIPROXY_API_KEY" not in env
    assert env["RAG_EXTERNAL_LLM_ALLOWED"] == "false"
    assert env["MEETINGBOT_DEMO_PROCESS"] == "1"
    assert env["STT_ACCESS_DB"] == env["RAG_ACCESS_DB"]
    assert env["STT_RAG_TOKEN_FILE"] == env["RAG_AUTH_TOKEN_FILE"]
    keys = [(state / p).read_text() for p in ("stt/local-token", "admin-key", "visitor-key")]
    assert len(set(keys)) == 3 and all(len(k) >= 32 for k in keys)
    assert all(k not in json.dumps(env) for k in keys)
    roots = json.loads(Path(env["RAG_SOURCE_ROOTS_FILE"]).read_text())
    assert Path(roots["roots"][0]["path"]).is_relative_to(state)
    assert "STT_PUBLIC_ORIGIN" not in env
    public = demo.prepare(state, 8985, 8986, "https://demo.example:10000")
    assert public["STT_PUBLIC_ORIGIN"] == "https://demo.example:10000"
    assert [(state / p).read_text() for p in ("stt/local-token", "admin-key", "visitor-key")] == keys


def test_existing_non_demo_data_and_symlink_are_rejected(tmp_path):
    existing = tmp_path / "private"
    existing.mkdir()
    sentinel = existing / "original.txt"
    sentinel.write_text("private")
    with pytest.raises(SystemExit, match="non-demo"):
        demo.prepare(existing, 8985, 8986)
    assert sentinel.read_text() == "private"
    assert not (existing / ".demo-instance").exists()
    alias = tmp_path / "alias"
    alias.symlink_to(existing, target_is_directory=True)
    with pytest.raises(SystemExit, match="symbolic"):
        demo.prepare(alias, 8985, 8986)
