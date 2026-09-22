#!/usr/bin/env python3
"""First native installation; subsequent launches use the generated desktop files."""
import argparse
import os
import platform
import shlex
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def python_in(directory):
    return directory / ("Scripts/python.exe" if WINDOWS else "bin/python")


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def check_platform():
    machine = os.environ.get("PROCESSOR_ARCHITEW6432", platform.machine()).lower()
    if WINDOWS and (machine not in {"amd64", "x86_64"} or sys.maxsize <= 2 ** 32):
        raise SystemExit("Meetingbot native Windows installation requires Windows x64 and 64-bit Python. "
                         "Windows ARM and 32-bit Python are not supported.")


def npm_command():
    npm = shutil.which("npm")
    if not WINDOWS:
        return [npm]
    node = shutil.which("node")
    # Calling npm.cmd through cmd.exe reparses spaces and shell metacharacters.
    # Node's distributed JS entry point accepts an ordinary subprocess argv list.
    for executable in (npm, node):
        candidate = Path(executable).resolve().parent / "node_modules/npm/bin/npm-cli.js"
        if candidate.is_file():
            return [node, candidate]
    raise SystemExit("Cannot locate npm-cli.js. Repair your Node.js installation, then retry Install-Windows.cmd.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-launch", action="store_true")
    args = parser.parse_args()
    check_platform()
    missing = [name for name in ("node", "npm", "ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        raise SystemExit("Install Node.js LTS and FFmpeg once, then retry. Missing: " + ", ".join(missing)
                         + ". Alternatively use docker compose up --build -d (only Docker required).")
    npm = npm_command()
    uv = shutil.which("uv")
    if not uv:
        bootstrap = ROOT / ".bootstrap"
        if not python_in(bootstrap).exists():
            venv.create(bootstrap, with_pip=True)
        run([python_in(bootstrap), "-m", "pip", "install", "--index-url", "https://pypi.org/simple", "uv>=0.8,<1"])
        uv = bootstrap / ("Scripts/uv.exe" if WINDOWS else "bin/uv")
    # uv provisions Python 3.12 automatically; environments remain project-local.
    run([uv, "sync", "--project", ROOT / "backend", "--python", "3.12", "--frozen", "--extra", "speech", "--no-dev"])
    run([uv, "sync", "--project", ROOT / "rag", "--python", "3.12", "--frozen", "--no-dev"])
    run([*npm, "ci"], cwd=ROOT / "frontend")
    run([*npm, "run", "build"], cwd=ROOT / "frontend")
    executable = python_in(ROOT / "backend" / ".venv")
    launcher = ROOT / "scripts" / "launch.py"
    if WINDOWS:
        (ROOT / "Meetingbot.cmd").write_text(
            '@echo off\nsetlocal DisableDelayedExpansion\n'
            '"%~dp0backend\\.venv\\Scripts\\python.exe" "%~dp0scripts\\launch.py" %*\n'
            'set "meetingbot_exit=%errorlevel%"\npause\nexit /b %meetingbot_exit%\n', encoding="utf-8")
    else:
        target = ROOT / ("Meetingbot.command" if sys.platform == "darwin" else "Meetingbot.sh")
        target.write_text("#!/bin/sh\nexec " + shlex.quote(str(executable)) + " " + shlex.quote(str(launcher)) + "\n", encoding="utf-8")
        target.chmod(0o755)
    print("Installation complete. Open the Meetingbot launcher in this folder next time.")
    if not args.no_launch:
        run([executable, launcher])


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
