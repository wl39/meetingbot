import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("native_install", Path(__file__).resolve().parents[1] / "install.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


@pytest.fixture
def windows_install(tmp_path, monkeypatch):
    root = tmp_path / "Meetingbot 회의 자료 & notes"
    root.mkdir()
    tools = root / "Program Files/nodejs"
    tools.mkdir(parents=True)
    npm_cli = tools / "node_modules/npm/bin/npm-cli.js"
    npm_cli.parent.mkdir(parents=True)
    npm_cli.touch()
    applications = {"node": tools / "node.exe", "npm": tools / "npm.cmd",
                    "ffmpeg": root / "ffmpeg.exe", "ffprobe": root / "ffprobe.exe", "uv": root / "uv.exe"}
    monkeypatch.setattr(installer, "ROOT", root)
    monkeypatch.setattr(installer, "WINDOWS", True)
    monkeypatch.setattr(installer.platform, "machine", lambda: "AMD64")
    monkeypatch.setattr(installer.sys, "maxsize", 2 ** 63 - 1)
    monkeypatch.delenv("PROCESSOR_ARCHITEW6432", raising=False)
    monkeypatch.setattr(installer.shutil, "which", lambda name: str(applications[name]) if name in applications else None)
    monkeypatch.setattr(installer.sys, "argv", ["install.py", "--no-launch"])
    return root, applications, npm_cli


def test_windows_installer_runs_npm_without_command_shell_and_preserves_paths(windows_install, monkeypatch):
    root, applications, npm_cli = windows_install
    calls = []
    monkeypatch.setattr(installer, "run", lambda args, **kwargs: calls.append((args, kwargs)))

    installer.main()

    frontend = [(args, kwargs) for args, kwargs in calls if kwargs.get("cwd") == root / "frontend"]
    assert frontend == [
        ([str(applications["node"]), npm_cli, "ci"], {"cwd": root / "frontend"}),
        ([str(applications["node"]), npm_cli, "run", "build"], {"cwd": root / "frontend"}),
    ]
    assert len(calls) == 4  # two uv syncs, then two npm commands; no launch
    launcher = (root / "Meetingbot.cmd").read_text()
    assert '"%~dp0backend\\.venv\\Scripts\\python.exe"' in launcher
    assert "DisableDelayedExpansion" in launcher
    assert launcher.index('set "meetingbot_exit=%errorlevel%"') < launcher.index("pause")
    assert launcher.rstrip().endswith("exit /b %meetingbot_exit%")


@pytest.mark.parametrize("machine,bits", [("ARM64", 64), ("AMD64", 32), ("x86", 32)])
def test_unsupported_windows_fails_before_installing(windows_install, monkeypatch, machine, bits):
    monkeypatch.setattr(installer.platform, "machine", lambda: machine)
    monkeypatch.setattr(installer.sys, "maxsize", 2 ** (bits - 1) - 1)
    monkeypatch.setattr(installer, "run", lambda *_args, **_kwargs: pytest.fail("must fail before install"))

    with pytest.raises(SystemExit, match="Windows x64"):
        installer.main()


def test_windows_arm_emulation_is_rejected(windows_install, monkeypatch):
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "ARM64")
    with pytest.raises(SystemExit, match="Windows x64"):
        installer.check_platform()


def test_missing_npm_entry_fails_before_large_downloads(windows_install, monkeypatch):
    _, _, npm_cli = windows_install
    npm_cli.unlink()
    monkeypatch.setattr(installer, "run", lambda *_args, **_kwargs: pytest.fail("must fail before install"))

    with pytest.raises(SystemExit, match="npm-cli.js"):
        installer.main()


def test_missing_ffprobe_fails_before_installing(windows_install, monkeypatch):
    _, applications, _ = windows_install
    applications.pop("ffprobe")
    monkeypatch.setattr(installer, "run", lambda *_args, **_kwargs: pytest.fail("must fail before install"))

    with pytest.raises(SystemExit, match="ffprobe"):
        installer.main()


POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


@pytest.mark.skipif(not POWERSHELL, reason="PowerShell runtime required (runs in Windows CI)")
def test_windows_bootstrap_orchestration_isolated(tmp_path):
    script = Path(__file__).resolve().parents[1] / "install-windows.ps1"
    quoted_script = str(script).replace("'", "''")
    harness = tmp_path / "bootstrap-test.ps1"
    harness.write_text(
        f". '{quoted_script}'\n" + r'''
function Assert-True($Condition, $Message) { if (-not $Condition) { throw $Message } }
# Dot-sourcing must not run any setup. Replace every external action below.
function Assert-MeetingbotWindows { }
function Update-MeetingbotPath { $script:Refreshes++ }
$script:Refreshes = 0
$script:Packages = @()
$script:PythonReady = $false
$script:NodeReady = $false
$script:AudioReady = $false
$script:PythonArguments = @()
function Fake-Python {
    $script:PythonArguments = @($args)
    $global:LASTEXITCODE = 0
}
function Find-MeetingbotPython { if ($script:PythonReady) { return 'Fake-Python' }; return $null }
function Assert-MeetingbotNode { return $script:NodeReady }
function Find-MeetingbotApplication($Name) {
    if ($script:AudioReady -and $Name -in @('ffmpeg.exe', 'ffprobe.exe')) { return $Name }
    return $null
}
function Install-MeetingbotDependency($Package, $Options) {
    $script:Packages += $Package
    switch ($Package) {
        'Python.Python.3.12' { $script:PythonReady = $true }
        'OpenJS.NodeJS.22' { $script:NodeReady = $true }
        'Gyan.FFmpeg' { $script:AudioReady = $true }
        default { throw 'Unexpected package' }
    }
}
Invoke-MeetingbotWindowsInstall -SkipLaunch
Assert-True (($script:Packages -join ',') -eq 'Python.Python.3.12,OpenJS.NodeJS.22,Gyan.FFmpeg') 'wrong dependency order'
Assert-True ($script:PythonArguments.Count -eq 2) 'wrong Python argument count'
Assert-True ($script:PythonArguments[0] -eq (Join-Path $script:MeetingbotRoot 'scripts\install.py')) 'checkout path split'
Assert-True ($script:PythonArguments[1] -eq '--no-launch') 'no-launch option lost'
$script:Packages = @()
Invoke-MeetingbotWindowsInstall -SkipLaunch
Assert-True ($script:Packages.Count -eq 0) 'existing tools were reinstalled'
function Fake-Python { $global:LASTEXITCODE = 42 }
try { Invoke-MeetingbotWindowsInstall -SkipLaunch; throw 'failure was ignored' }
catch { Assert-True ($_.Exception.Data['ExitCode'] -eq 42) 'failure code was lost' }
Write-Output 'bootstrap isolated checks passed'
''', encoding="utf-8-sig")
    result = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "bootstrap isolated checks passed" in result.stdout
