import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location("portable_launcher", Path(__file__).resolve().parents[2] / "scripts/launch.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    settings = SimpleNamespace(data_dir=tmp_path, rag_token_file=None)
    monkeypatch.setattr(launcher, "prepare_environment", lambda: (settings, {}, "private-key"))
    monkeypatch.setattr(launcher.sys, "argv", ["launch.py", "--no-browser"])
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    monkeypatch.setattr(launcher, "WINDOWS", False)
    return tmp_path


def test_reopening_validates_both_existing_services(setup, monkeypatch):
    verified = []
    monkeypatch.setattr(launcher, "port_open", lambda _: True)
    monkeypatch.setattr(launcher, "verify_service", lambda url, token: verified.append((url, token)))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must reuse both services"))
    launcher.main()
    assert [url for url, _ in verified] == ["http://127.0.0.1:8765/api/stt/health", "http://127.0.0.1:8766/api/rag/workspaces"]
    assert all(token == "private-key" for _, token in verified)


def test_foreign_service_is_never_stopped(setup, monkeypatch):
    monkeypatch.setattr(launcher, "port_open", lambda _: True)

    def foreign(*_):
        raise SystemExit("foreign service")

    monkeypatch.setattr(launcher, "verify_service", foreign)
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not start"))
    with pytest.raises(SystemExit, match="foreign service"):
        launcher.main()


def test_reopening_starts_only_missing_rag_and_owns_only_its_process(setup, monkeypatch):
    executable = setup / "python"
    executable.touch()
    monkeypatch.setattr(launcher, "environment_python", lambda _: executable)
    port_calls = []

    def ports(port):
        port_calls.append(port)
        return not (len(port_calls) == 2 and port == 8766)

    monkeypatch.setattr(launcher, "port_open", ports)
    monkeypatch.setattr(launcher, "verify_service", lambda *_: None)
    calls = []

    class Process:
        polls = 0
        waited = False

        def poll(self):
            self.polls += 1
            return None if self.polls == 1 else 1

        def terminate(self):
            pytest.fail("already stopped process should not be terminated")

        def wait(self, timeout):
            self.waited = True

    process = Process()

    def spawn(args, **kwargs):
        calls.append(args)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", spawn)
    with pytest.raises(SystemExit, match="service stopped"):
        launcher.main()
    assert len(calls) == 1 and "meetingbot_rag.app:create_app" in calls[0]
    assert process.waited


def test_launching_outside_checkout_keeps_relative_data_paths_in_checkout(tmp_path, monkeypatch):
    from app.modules.stt.settings import Settings

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(launcher, "ROOT", checkout)
    monkeypatch.setenv("RAG_DATA_DIR", "documents-data")
    settings = Settings(_env_file=None, data_dir=Path("private-data"), access_db=Path("access.sqlite3"))
    monkeypatch.setattr("app.modules.stt.settings.Settings", lambda: settings)

    prepared, environment, token = launcher.prepare_environment()

    assert prepared.data_dir == checkout / "private-data"
    assert environment["STT_DATA_DIR"] == str(checkout / "private-data")
    assert environment["RAG_DATA_DIR"] == str(checkout / "documents-data")
    assert environment["STT_ACCESS_DB"] == environment["RAG_ACCESS_DB"] == str(checkout / "access.sqlite3")
    assert environment["PYTHONUTF8"] == "1"
    assert environment["PYTHONIOENCODING"] == "utf-8"
    assert Path(environment["RAG_AUTH_TOKEN_FILE"]).read_text() == token
    assert list(elsewhere.iterdir()) == []


def test_windows_shutdown_signals_only_owned_processes_then_closes_job(monkeypatch):
    events = []
    monkeypatch.setattr(launcher, "WINDOWS", True)
    monkeypatch.setattr(launcher.signal, "CTRL_BREAK_EVENT", 1, raising=False)

    class Process:
        def poll(self):
            return None

        def send_signal(self, value):
            events.append(("signal", value))

        def wait(self, timeout=None):
            events.append(("wait", timeout))

    job = SimpleNamespace(close=lambda: events.append(("job", "closed")))
    launcher.stop_processes([Process()], job)
    assert [event[0] for event in events] == ["signal", "wait", "job"]
    assert events[0][1] == launcher.signal.CTRL_BREAK_EVENT


def test_windows_shutdown_kills_unresponsive_process_and_closes_job(monkeypatch):
    events = []
    monkeypatch.setattr(launcher, "WINDOWS", True)
    monkeypatch.setattr(launcher.signal, "CTRL_BREAK_EVENT", 1, raising=False)

    class Process:
        def poll(self):
            return None

        def send_signal(self, value):
            raise OSError("process already exiting")

        def wait(self, timeout=None):
            if timeout is not None:
                raise subprocess.TimeoutExpired("test-child", timeout)
            events.append("reaped")

        def kill(self):
            events.append("killed")

    job = SimpleNamespace(close=lambda: events.append("job closed"))
    launcher.stop_processes([Process()], job)
    assert events == ["killed", "reaped", "job closed"]


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows Job Objects")
def test_native_windows_job_closes_child_and_grandchild():
    from ctypes import wintypes

    job = launcher.WindowsJob()
    api = job.api
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", "import subprocess,sys,time; sys.stdin.readline(); "
         "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
         "print(child.pid,flush=True); time.sleep(60)"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    child_handle = None
    try:
        job.add(process)
        process.stdin.write("start\n")
        process.stdin.flush()
        child_pid = int(process.stdout.readline())
        child_handle = api.OpenProcess(0x00100000, False, child_pid)  # SYNCHRONIZE
        assert child_handle
        job.close()
        process.wait(timeout=10)
        assert api.WaitForSingleObject(child_handle, 10000) == 0
    finally:
        job.close()
        if child_handle:
            api.CloseHandle(child_handle)
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        process.stdin.close()
        process.stdout.close()


def test_existing_rag_configuration_resolves_bridge_token_from_checkout(tmp_path, monkeypatch):
    from app.modules.stt.settings import Settings

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".env.rag").write_text("# Existing configuration\n")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(launcher, "ROOT", checkout)
    settings = Settings(_env_file=None, data_dir=Path("private-data"), rag_token_file=Path("rag/admin-token"))
    monkeypatch.setattr("app.modules.stt.settings.Settings", lambda: settings)

    prepared, environment, _ = launcher.prepare_environment()

    assert prepared.rag_token_file == checkout / "rag/admin-token"
    assert environment["STT_RAG_TOKEN_FILE"] == str(checkout / "rag/admin-token")
    assert not (checkout / ".rag-data").exists()
    assert list(elsewhere.iterdir()) == []
