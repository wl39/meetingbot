#!/usr/bin/env python3
"""Run an isolated anonymous demo. No existing service or private data is reused."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def python_for(project):
    return ROOT / project / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def default_data():
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/MeetingbotDemo"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MeetingbotDemo"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "meetingbot-demo"


def isolated_directory(path):
    if path.is_symlink():
        raise SystemExit("Demo data must be a separate real directory.")
    marker = path / ".demo-instance"
    if path.exists() and not marker.is_file() and any(path.iterdir()):
        raise SystemExit("Refusing to open a non-demo data directory anonymously: " + str(path))
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    marker.write_text("meetingbot-demo-v1\n", encoding="utf-8")


def prepare(data, port, rag_port, origin="", fake=False):
    sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "rag")]
    from app.modules.stt.settings import Settings as SpeechSettings
    from meetingbot_access import AccessStore
    from meetingbot_rag.settings import Settings as RagSettings

    source_speech, source_rag = SpeechSettings(), RagSettings()
    source_speech.data_dir = (ROOT / source_speech.data_dir).resolve()
    source_rag.data_dir = (ROOT / source_rag.data_dir).resolve()
    if source_rag.model_cache_dir:
        source_rag.model_cache_dir = (ROOT / source_rag.model_cache_dir).resolve()
    data = data.expanduser().absolute()
    if data.is_symlink():
        raise SystemExit("Demo data must not be a symbolic link.")
    data = data.resolve()
    # Even an accidentally supplied source-state path must not expose private records.
    forbidden = {source_speech.data_dir.resolve(), source_rag.data_dir.resolve()}
    if data.resolve() in forbidden or any(p in forbidden for p in data.resolve().parents):
        raise SystemExit("Choose a data directory outside the existing private instance.")
    isolated_directory(data)
    speech, rag = data / "stt", data / "rag"
    isolated_directory(speech)
    isolated_directory(rag)
    s = SpeechSettings(_env_file=None, data_dir=speech, demo_mode=True)
    s.prepare()
    s.local_token()
    access_db = data / "access.sqlite3"
    access = AccessStore(speech / "local-token", access_db)
    # Files are intentionally local; key values are never printed in logs.
    for role in ("visitor", "admin"):
        path = data / (role + "-key")
        if not path.exists():
            issued = access.issue_key("데모 " + role, role)
            path.write_text(issued["key"], encoding="utf-8")
            path.chmod(0o600)
    model_dir = speech / "models"
    source_manifest = source_speech.data_dir / "models/manifest.json"
    if source_manifest.is_file():
        shutil.copy2(source_manifest, model_dir / "manifest.json")
    # External engine environments are reused for inference, never installed from the demo.
    engines = source_speech.data_dir / "engines"
    if engines.is_dir() and not (speech / "engines").exists():
        (speech / "engines").symlink_to(engines.resolve(), target_is_directory=True)
    docs = data / "sample-documents"
    docs.mkdir(exist_ok=True)
    sample = docs / "회의-운영-가이드.md"
    if not sample.exists():
        sample.write_text("# 데모 회사의 회의 운영 가이드\n\n이 문서는 공개 체험용 가상 자료입니다.\n\n"
                          "## 로그 보관\n운영 서버 로그는 90일 동안 보관합니다. 개발 서버 로그는 30일 동안 보관합니다.\n\n"
                          "## 회의 준비\n회의 주최자는 하루 전에 안건을 공유합니다. 참석자는 회의 시작 5분 전에 접속합니다.\n\n"
                          "## 회의 후속 작업\n회의록에는 결정 사항, 담당자, 기한을 기록합니다. 담당자는 다음 영업일까지 내용을 확인합니다.\n",
                          encoding="utf-8")
    roots = data / "source-roots.json"
    roots.write_text(json.dumps({"roots": [{"id": "demo", "label": "공개 데모 자료", "path": str(docs)}]}, ensure_ascii=False), encoding="utf-8")
    local = f"http://127.0.0.1:{port}"
    from urllib.parse import urlsplit
    hosts = ["127.0.0.1", "localhost"] + ([urlsplit(origin).hostname] if origin else [])
    origins = [local, f"http://localhost:{port}"] + ([origin] if origin else [])
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STT_", "RAG_"))}
    env.update({
        "MEETINGBOT_DEMO_PROCESS": "1", "PYTHONUNBUFFERED": "1", "PYANNOTE_METRICS_ENABLED": "0",
        "TOKENIZERS_PARALLELISM": "false", "HF_HUB_DISABLE_TELEMETRY": "1", "LANGSMITH_TRACING": "false",
        "STT_DATA_DIR": str(speech), "STT_DEMO_MODE": "true", "STT_ACCESS_DB": str(access_db),
        "STT_ENGINE": "fake" if fake else "real", "STT_ORIGINS": json.dumps(origins),
        "STT_ALLOWED_HOSTS": json.dumps(hosts), "STT_RAG_BASE_URL": f"http://127.0.0.1:{rag_port}",
        "STT_RAG_TOKEN_FILE": str(speech / "local-token"), "STT_DEFAULT_MODEL": "small",
        "RAG_DATA_DIR": str(rag), "RAG_DEMO_MODE": "true", "RAG_ACCESS_DB": str(access_db),
        "RAG_AUTH_TOKEN_FILE": str(speech / "local-token"), "RAG_SOURCE_ROOTS_FILE": str(roots),
        "RAG_MODEL_CACHE_DIR": str((source_rag.model_cache_dir or source_rag.data_dir / "models").resolve()),
        "RAG_ALLOWED_HOSTS": json.dumps(["127.0.0.1", "localhost"]),
        "RAG_ORIGINS": json.dumps([f"http://127.0.0.1:{rag_port}"]), "RAG_ACCESS_MODE": "local",
        "RAG_WORKSPACE_URL": origin or local, "RAG_EXTERNAL_LLM_ALLOWED": "false",
        "RAG_HISTORY_DAYS": "1",
    })
    if origin:
        # Only the front gateway is public; RAG stays on loopback and receives validated origins.
        env["STT_PUBLIC_ORIGIN"] = origin
    return env


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            raise SystemExit(f"Port {port} is in use. No existing service was stopped.") from None


def tailscale_binary():
    return shutil.which("tailscale") or ("/Applications/Tailscale.app/Contents/MacOS/Tailscale" if sys.platform == "darwin" else "tailscale")


def main():
    parser = argparse.ArgumentParser(description="키 없이 체험하는 별도 회의봇 데모")
    parser.add_argument("--public", action="store_true", help="Tailscale Funnel 10000 포트로 공개")
    parser.add_argument("--fake", action="store_true", help="실제 음성 인식 대신 검증용 결과")
    parser.add_argument("--data-dir", type=Path, default=default_data())
    parser.add_argument("--port", type=int, default=8875)
    parser.add_argument("--rag-port", type=int, default=8876)
    args = parser.parse_args()
    if not all(python_for(p).exists() for p in ("backend", "rag")):
        raise SystemExit("먼저 scripts/install.py로 설치해 주세요.")
    if Path(sys.prefix).resolve() != (ROOT / "backend/.venv").resolve():
        os.execv(str(python_for("backend")), [str(python_for("backend")), str(Path(__file__).resolve()), *sys.argv[1:]])
    for port in (args.port, args.rag_port):
        free_port(port)
    if args.port == args.rag_port:
        raise SystemExit("Choose two different ports.")
    origin, tunnel = "", tailscale_binary()
    if args.public:
        status = json.loads(subprocess.check_output([tunnel, "status", "--json"], text=True))
        if status.get("BackendState") != "Running":
            raise SystemExit("먼저 Tailscale에 연결해 주세요.")
        serve = json.loads(subprocess.check_output([tunnel, "serve", "status", "--json"], text=True))
        if "10000" in (serve.get("TCP") or {}):
            raise SystemExit("Tailscale 10000 포트가 사용 중입니다. 기존 연결은 변경하지 않았습니다.")
        origin = "https://" + status["Self"]["DNSName"].rstrip(".") + ":10000"
    env = prepare(args.data_dir, args.port, args.rag_port, origin, args.fake)
    if not (ROOT / "frontend/dist/index.html").is_file():
        raise SystemExit("먼저 frontend에서 npm run build를 실행해 주세요.")
    processes, handles, published = [], [], False
    logs = args.data_dir.expanduser().absolute() / "logs"
    logs.mkdir(exist_ok=True)
    try:
        for project, target, port in (("rag", "meetingbot_rag.app:create_app", args.rag_port), ("backend", "app.main:create_app", args.port)):
            output = (logs / (project + ".log")).open("a", encoding="utf-8")
            handles.append(output)
            processes.append(subprocess.Popen([str(python_for(project)), "-m", "uvicorn", target, "--factory",
                "--host", "127.0.0.1", "--port", str(port), "--no-access-log", "--ws-max-size", "500000", "--ws-max-queue", "8"],
                cwd=ROOT / project, env=env, stdout=output, stderr=output))
        import urllib.request
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(120):
            if any(p.poll() is not None for p in processes):
                raise SystemExit("데모 시작 실패. 로그 폴더: " + str(logs))
            try:
                with opener.open(f"http://127.0.0.1:{args.port}/api/access/session", timeout=1) as r:
                    if json.load(r).get("demo"):
                        break
            except OSError:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit("데모 연결 시간 초과. 로그 폴더: " + str(logs))
        if args.public:
            # Mark before invoking: Ctrl+C during activation also removes our port.
            published = True
            subprocess.run([tunnel, "funnel", "--bg", "--https=10000", f"http://127.0.0.1:{args.port}"], check=True)
        print("공개 데모 준비: " + (origin or f"http://127.0.0.1:{args.port}"), flush=True)
        print("슈퍼관리자 키 파일: " + env["STT_RAG_TOKEN_FILE"], flush=True)
        print("이 창을 유지하세요. Ctrl+C로 데모와 이 데모의 공개 연결을 종료합니다.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if published:
            subprocess.run([tunnel, "funnel", "--https=10000", "off"], check=False)
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=20)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    main()
