#!/usr/bin/env python3
"""Portable foreground supervisor. Double-click launchers call this after installation."""
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


class WindowsJob:
    """Keep API processes and their inference workers owned by this launcher."""

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
                ("scheduling", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits), ("io_counters", ctypes.c_uint64 * 6),
                ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t),
            ]

        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.api.CreateJobObjectW.restype = wintypes.HANDLE
        self.api.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.api.SetInformationJobObject.restype = wintypes.BOOL
        self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.api.OpenProcess.restype = wintypes.HANDLE
        self.api.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.api.AssignProcessToJobObject.restype = wintypes.BOOL
        self.api.CloseHandle.argtypes = [wintypes.HANDLE]
        self.api.CloseHandle.restype = wintypes.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def add(self, process):
        import ctypes

        handle = self.api.OpenProcess(0x0101, False, process.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self.api.AssignProcessToJobObject(self.handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self.api.CloseHandle(handle)

    def close(self):
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None


def stop_processes(processes, job):
    try:
        for process in processes:
            if process.poll() is None:
                try:
                    if WINDOWS:
                        process.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        process.terminate()
                except OSError:
                    pass  # The child may have exited between poll and signal.
        deadline = time.monotonic() + 20
        for process in processes:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    finally:
        if job:
            # Also releases any grandchildren still loading/inferencing models.
            job.close()


def environment_python(project):
    return ROOT / project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def project_path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def verify_service(url, token):
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            if response.status != 200:
                raise RuntimeError("Unexpected service")
    except (OSError, RuntimeError):
        raise SystemExit("Another service or installation occupies a Meetingbot port. No service was stopped.") from None


def prepare_environment():
    environment = os.environ.copy()
    # Native existing installations keep their own .env settings and data locations.
    sys.path.insert(0, str(ROOT / "backend"))
    from app.modules.stt.settings import Settings

    settings = Settings()
    # Desktop launchers inherit their caller's working directory. Keep .env paths
    # anchored to this installation, including paths passed to the two child APIs.
    settings.data_dir = project_path(settings.data_dir)
    if settings.access_db:
        settings.access_db = project_path(settings.access_db)
    if settings.rag_token_file:
        settings.rag_token_file = project_path(settings.rag_token_file)
    settings.prepare()
    token = settings.local_token()
    rag_data = project_path(environment.get("RAG_DATA_DIR", ROOT / ".rag-data"))
    rag_config = ROOT / ".env.rag"
    if not rag_config.exists() or environment.get("MEETINGBOT_CONTAINER") == "1":
        rag_data.mkdir(parents=True, exist_ok=True)
        admin = rag_data / "admin-token"
        if not admin.exists():
            admin.write_text(token, encoding="utf-8")
        admin.chmod(0o600)
        config = rag_data / "source-roots.json"
        documents = rag_data / "documents"
        documents.mkdir(exist_ok=True)
        if not config.exists():
            config.write_text(json.dumps({"roots": [{"id": "meeting-docs", "label": "회의 자료", "path": str(documents)}]},
                                        ensure_ascii=False), encoding="utf-8")
        environment.update(RAG_DATA_DIR=str(rag_data), RAG_AUTH_TOKEN_FILE=str(admin),
                           RAG_SOURCE_ROOTS_FILE=str(config), RAG_WORKSPACE_URL="http://127.0.0.1:8765")
        settings.rag_token_file = admin
    environment.update(STT_DATA_DIR=str(settings.data_dir), PYANNOTE_METRICS_ENABLED="0", PYTHONUNBUFFERED="1",
                       PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    access_db = settings.access_db or settings.data_dir / "access.sqlite3"
    environment.update(STT_ACCESS_DB=str(access_db), RAG_ACCESS_DB=str(access_db))
    if settings.rag_token_file:
        environment["STT_RAG_TOKEN_FILE"] = str(settings.rag_token_file)
    return settings, environment, token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    settings, environment, token = prepare_environment()
    url = "http://127.0.0.1:8765/#token=" + token
    running_stt = port_open(8765)
    running_rag = port_open(8766)
    if running_stt:
        # Only reuse a service which accepts this installation's key.
        verify_service("http://127.0.0.1:8765/api/stt/health", token)
    if running_rag:
        rag_token = settings.rag_token_file.read_text().strip() if settings.rag_token_file else token
        verify_service("http://127.0.0.1:8766/api/rag/workspaces", rag_token)
    if running_stt and running_rag:
        if not args.no_browser and not args.container:
            webbrowser.open(url)
        print("Meetingbot is already running. Open the installed launcher to reconnect.")
        return
    processes = []
    logs = settings.data_dir / "logs"
    logs.mkdir(exist_ok=True)
    handles = []
    job = None
    try:
        if WINDOWS:
            job = WindowsJob()
        for project, target, port in (("rag", "meetingbot_rag.app:create_app", 8766), ("backend", "app.main:create_app", 8765)):
            if (port == 8765 and running_stt) or (port == 8766 and running_rag):
                continue
            executable = environment_python(project)
            if not executable.is_file():
                raise SystemExit("Run scripts/install.py once before opening Meetingbot.")
            output = (logs / (project + ".log")).open("a", encoding="utf-8")
            handles.append(output)
            process = subprocess.Popen(
                [str(executable), "-m", "uvicorn", target, "--factory", "--host",
                 "0.0.0.0" if args.container and port == 8765 else "127.0.0.1", "--port", str(port),
                 "--no-access-log"], cwd=ROOT / project, env=environment, stdout=output, stderr=output,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
            )
            processes.append(process)
            if job:
                try:
                    job.add(process)
                except OSError:
                    process.kill()
                    raise SystemExit("Windows could not attach the service to this launcher. No existing service was stopped.") from None
        for _ in range(120):
            if any(process.poll() is not None for process in processes):
                raise SystemExit("Meetingbot could not start. See the logs folder: " + str(logs))
            if port_open(8765) and port_open(8766):
                break
            time.sleep(0.5)
        else:
            raise SystemExit("Meetingbot startup timed out. See the logs folder: " + str(logs))
        if not args.no_browser and not args.container:
            webbrowser.open(url)
        # Explicit access-link command reads this local file; never place the key in server logs.
        print("Meetingbot is ready at http://127.0.0.1:8765. Keep this launcher open. Ctrl+C stops both services.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        raise SystemExit("A Meetingbot service stopped. Both services are stopping; reopen the launcher to recover.")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            stop_processes(processes, job)
        finally:
            for handle in handles:
                handle.close()


if __name__ == "__main__":
    def stop(signum, frame):
        raise KeyboardInterrupt

    # Docker sends SIGTERM to this supervisor; give both APIs their graceful shutdown.
    signal.signal(signal.SIGTERM, stop)
    main()
