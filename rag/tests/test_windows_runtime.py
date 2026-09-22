"""Locale/file-lifetime regressions plus native Windows source and lock checks."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import KEY, FakeModel
from fastapi.testclient import TestClient
from test_rag import wait
from test_uploads import begin, put

from meetingbot_rag import process_lock, sources
from meetingbot_rag.app import create_app
from meetingbot_rag.db import open_database
from meetingbot_rag.sources import RagError, SourceBrowserService, is_link_or_reparse
from meetingbot_rag.windows_sources import opened_windows


def test_unicode_startup_upload_and_index_under_legacy_text_locale(env, monkeypatch):
    settings, _ = env
    original_open = Path.open

    def legacy_open(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if "b" not in mode and encoding is None:
            encoding = "cp1252"
        return original_open(path, mode, buffering, encoding, errors, newline)

    monkeypatch.setattr(Path, "open", legacy_open)
    # Parser subprocess pipes must also preserve Korean and characters outside cp1252.
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    data = "# 회의 정책 📝\n로그 보관 기간은 75일입니다.\n".encode("utf-8")
    app = create_app(settings, FakeModel())
    with TestClient(app, headers={"Authorization": "Bearer " + KEY}) as client:
        row = begin(client, [{"path": "정책/회의📝.md", "size": len(data)}]).json()
        assert put(client, row, data).status_code == 200
        response = client.post(f"/api/rag/uploads/{row['id']}/commit", json={})
        assert response.status_code == 200, response.text
        result = response.json()
        wid = result["workspace"]["id"]
        job = wait(client, wid, result["job"]["job_id"])
        assert job["state"] == "READY", job
        assert job["result"]["documents"][0]["relative_path"] == "정책/회의📝.md"
        manifests = list(settings.data_dir.glob("workspaces/*/revisions/*/manifest.json"))
        assert len(manifests) == 1
        assert "회의📝.md" in manifests[0].read_bytes().decode("utf-8")
        assert client.delete(f"/api/rag/workspaces/{wid}").status_code == 200


def test_short_lived_databases_close_commit_rollback_and_escape_file_uri(tmp_path):
    path = tmp_path / "회의 #100%.sqlite"
    with open_database(path) as connection:
        connection.execute("CREATE TABLE sample(value TEXT)")
        connection.execute("INSERT INTO sample VALUES('kept')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT * FROM sample")
    with pytest.raises(ValueError):
        with open_database(path) as connection:
            connection.execute("INSERT INTO sample VALUES('rolled back')")
            raise ValueError("rollback")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT * FROM sample")
    with open_database(path, readonly=True) as connection:
        assert connection.execute("SELECT value FROM sample").fetchall() == [("kept",)]
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO sample VALUES('forbidden')")
    # Windows rejects this rename if a database connection still owns the file.
    path.rename(path.with_suffix(".moved"))


@pytest.mark.parametrize("part", ["CON.txt", "COM².md", "secrets ", "credentials.", "a?b"])
def test_windows_shared_source_rejects_device_and_alias_components(monkeypatch, part):
    monkeypatch.setattr(sources, "os", SimpleNamespace(name="nt"))
    service = SourceBrowserService(SimpleNamespace(max_depth=12))
    with pytest.raises(RagError, match="PATH_DENIED"):
        service.parts(part)


def test_junction_attribute_is_excluded_even_when_not_a_symlink():
    entry = SimpleNamespace(
        is_symlink=lambda: False,
        stat=lambda **kwargs: SimpleNamespace(st_file_attributes=0x0410),
    )
    assert is_link_or_reparse(entry)


def test_windows_process_lock_initializes_and_locks_byte_zero(tmp_path, monkeypatch):
    seen = []

    def locking(fd, mode, size):
        assert os.lseek(fd, 0, os.SEEK_CUR) == 0
        seen.append((mode, size, os.read(fd, 1)))

    monkeypatch.setattr(process_lock, "os", SimpleNamespace(name="nt", SEEK_END=os.SEEK_END))
    monkeypatch.setitem(sys.modules, "msvcrt", SimpleNamespace(LK_NBLCK=2, locking=locking))
    with process_lock.acquire_process_lock(tmp_path / "service.lock"):
        assert seen == [(2, 1, b"\0")]


def test_process_lock_excludes_other_process_until_closed(tmp_path):
    path = tmp_path / "service.lock"
    code = (
        "import sys\n"
        "from meetingbot_rag.process_lock import acquire_process_lock\n"
        "try:\n"
        "    lock = acquire_process_lock(sys.argv[1])\n"
        "except RuntimeError:\n"
        "    print('blocked')\n"
        "else:\n"
        "    lock.close()\n"
        "    print('acquired')\n"
    )

    def probe():
        return subprocess.run(
            [sys.executable, "-c", code, str(path)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout.strip()

    with process_lock.acquire_process_lock(path):
        assert probe() == "blocked"
    assert probe() == "acquired"


@pytest.mark.skipif(os.name != "nt", reason="requires the native Win32 filesystem APIs")
def test_native_windows_read_and_directory_handles_prevent_replacement(tmp_path):
    folder = tmp_path.resolve() / "한글 문서"
    folder.mkdir()
    document = folder / "회의.txt"
    data = "Windows에서 읽는 문서 📝".encode("utf-8")
    document.write_bytes(data)
    with opened_windows(folder, ["회의.txt"], file=True) as descriptor:
        assert os.read(descriptor, len(data) + 1) == data
        with pytest.raises(OSError):
            document.rename(folder / "moved.txt")
        with pytest.raises(OSError):
            folder.rename(tmp_path / "moved")
    document.rename(folder / "moved.txt")


@pytest.mark.skipif(os.name != "nt", reason="requires native Windows junction support")
def test_native_windows_junction_is_listed_as_excluded_and_never_scanned(env, tmp_path):
    settings, root = env
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"must not be read")
    (root / "allowed.txt").write_bytes(b"allowed")
    link = root / "junction"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        check=True,
        capture_output=True,
        timeout=15,
    )
    try:
        service = SourceBrowserService(settings)
        listed = {row["name"]: row for row in service.entries("docs")["entries"]}
        assert listed["junction"]["reason"] == "SYMLINK_EXCLUDED"
        scanned = {row["relative_path"]: row for row in service.scan("docs", "")["files"]}
        assert scanned["junction"]["state"] == "EXCLUDED"
        assert scanned["allowed.txt"]["state"] == "INCLUDED"
        assert not any("secret" in name for name in scanned)
        with pytest.raises(RagError, match="SOURCE_UNAVAILABLE"):
            service.read("docs", "junction/secret.txt")
    finally:
        link.rmdir()
