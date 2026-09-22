#!/usr/bin/env python3
"""Pinned, private macOS arm64 CLIProxyAPI service for Meetingbot."""

import argparse
import hashlib
import json
import os
import platform
import plistlib
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

VERSION = "7.2.155"
SHA256 = "f90c503ce41a798c85b6f61dfe5fe8b812c1b889634f0c80d04ee376424fe305"
URL = f"https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/CLIProxyAPI_{VERSION}_darwin_aarch64.tar.gz"
BASE = Path.home() / "Library/Application Support/MeetingbotCLIProxy"
LOGS = Path.home() / "Library/Logs/MeetingbotCLIProxy"
LABEL = "com.meetingbot.cliproxy"
PLIST = Path.home() / f"Library/LaunchAgents/{LABEL}.plist"
ROOT = Path(__file__).resolve().parent.parent


def request(path):
    keys = json.loads((BASE / "credentials.json").read_text())
    req = Request(
        "http://127.0.0.1:8317/v0/management/" + path,
        headers={"Authorization": "Bearer " + keys["management_key"]},
    )
    with build_opener(ProxyHandler({})).open(req, timeout=20) as response:
        return json.load(response)


def start():
    running = (
        subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )
    if running:
        subprocess.run(
            ["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"], check=True
        )
    else:
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST)], check=True
        )
    print("CLIProxyAPI started on 127.0.0.1:8317")


def install():
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This installer targets macOS arm64 only.")
    os.umask(0o077)
    BASE.mkdir(parents=True, exist_ok=True)
    BASE.chmod(0o700)
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "proxy.tar.gz"
        with (
            build_opener().open(URL, timeout=60) as response,
            archive.open("wb") as out,
        ):
            shutil.copyfileobj(response, out)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
            raise SystemExit("SHA256 mismatch; installed files unchanged.")
        with tarfile.open(archive) as tar:
            for item in tar.getmembers():
                if not item.isfile() or "/" in item.name or item.name in {".", ".."}:
                    raise SystemExit("Unexpected archive entry")
            for item in tar.getmembers():
                dest = BASE / item.name
                if item.name == "cli-proxy-api":
                    dest = BASE / "cli-proxy-api.new"
                dest.write_bytes(tar.extractfile(item).read())
                dest.chmod(0o700 if item.name == "cli-proxy-api" else 0o600)
            (BASE / "cli-proxy-api.new").replace(BASE / "cli-proxy-api")
    (BASE / "auth").mkdir(exist_ok=True)
    (BASE / "auth").chmod(0o700)
    credentials = BASE / "credentials.json"
    if not credentials.exists():
        credentials.write_text(
            json.dumps(
                {
                    "api_key": secrets.token_urlsafe(36),
                    "management_key": secrets.token_urlsafe(36),
                }
            )
        )
    keys = json.loads(credentials.read_text())
    config = BASE / "config.yaml"
    if not config.exists():
        # JSON is also valid YAML. Existing runtime settings and credentials are preserved.
        config.write_text(
            json.dumps(
                {
                    "host": "127.0.0.1",
                    "port": 8317,
                    "auth-dir": str(BASE / "auth"),
                    "api-keys": [keys["api_key"]],
                    "remote-management": {
                        "allow-remote": False,
                        "secret-key": keys["management_key"],
                        "disable-control-panel": True,
                        "disable-auto-update-panel": True,
                    },
                    "debug": False,
                    "pprof": {"enable": False},
                    "plugins": {"enabled": False},
                    "commercial-mode": True,
                    "request-log": False,
                    "logging-to-file": False,
                    "usage-statistics-enabled": False,
                    "request-retry": 0,
                    "max-retry-credentials": 1,
                    "max-retry-interval": 0,
                    "quota-exceeded": {
                        "switch-project": False,
                        "switch-preview-model": False,
                    },
                    "codex": {
                        "identity-confuse": False,
                        "disable-codex-cloaking": True,
                        "live-media-relay": {"enabled": False},
                    },
                },
                indent=2,
            )
        )
    LOGS.mkdir(parents=True, exist_ok=True)
    LOGS.chmod(0o700)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(
        plistlib.dumps(
            {
                "Label": LABEL,
                "ProgramArguments": [
                    str(BASE / "cli-proxy-api"),
                    "-config",
                    str(config),
                ],
                "WorkingDirectory": str(BASE),
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": 10,
                "Umask": 63,
                "StandardOutPath": str(LOGS / "service.log"),
                "StandardErrorPath": str(LOGS / "error.log"),
            }
        )
    )
    env = ROOT / ".env.rag"
    if env.exists():
        lines = [
            line
            for line in env.read_text().splitlines()
            if not line.startswith("RAG_MANAGED_PROXY_DIR=")
        ]
        env.write_text(
            "\n".join(lines) + "\nRAG_MANAGED_PROXY_DIR=" + json.dumps(str(BASE)) + "\n"
        )
        env.chmod(0o600)
    start()
    print(
        f"Installed v{VERSION}, SHA256 verified. Restart RAG and use AI settings to connect Codex."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["install", "start", "stop", "status", "login"]
    )
    action = parser.parse_args().action
    if action == "install":
        install()
    elif action == "start":
        start()
    elif action == "stop":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=True
        )
    elif action == "login":
        os.umask(0o077)
        data = request("codex-auth-url?is_webui=true")
        (BASE / "pending-login.json").write_text(json.dumps(data))
        print("Open this official Codex login URL on this Mac:")
        print(data["url"])
    else:
        data = request("auth-files")
        count = sum(
            1
            for x in data.get("files", [])
            if x.get("type") == "codex" and not x.get("disabled")
        )
        print(
            json.dumps(
                {
                    "installed_version": VERSION,
                    "endpoint": "http://127.0.0.1:8317/v1",
                    "codex_accounts": count,
                }
            )
        )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError):
        raise SystemExit(
            "CLIProxyAPI operation failed; check service status and private configuration."
        ) from None
