import asyncio
import json
import time
from types import SimpleNamespace

import pytest
from starlette.requests import ClientDisconnect
from test_rag import create, search, wait

from meetingbot_rag.sources import UPLOAD_ROOT, RagError
from meetingbot_rag.uploads import UploadService


def begin(c, files=None, **extra):
    return c.post(
        "/api/rag/uploads",
        json={
            "name": "외부 기기 자료",
            "folder_name": "회의 자료",
            "files": files or [{"path": "운영/정책.md", "size": len(DATA)}],
            **extra,
        },
    )


DATA = "# 운영 정책\n로그 보관 기간은 75일입니다.\n".encode()


def put(c, row, data=DATA, index=0, **kwargs):
    return c.put(f"/api/rag/uploads/{row['id']}/files/{row['files'][index]['id']}", content=data, **kwargs)


def test_folder_upload_index_search_retry_and_delete(client):
    c, root, core = client
    original = root / "keep.txt"
    original.write_text("서버 원본")
    response = begin(c)
    assert response.status_code == 201, response.text
    row = response.json()
    assert c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).status_code == 409
    assert put(c, row).status_code == 200
    assert put(c, row).status_code == 200
    response = c.post(f"/api/rag/uploads/{row['id']}/commit", json={})
    assert response.status_code == 200, response.text
    result = response.json()
    ws = result["workspace"]
    assert ws["consent"] is None and ws["source"]["kind"] == "upload"
    assert ws["source"]["label"] == "회의 자료"
    again = c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).json()
    assert again["workspace"]["id"] == ws["id"] and again["job"]["job_id"] == result["job"]["job_id"]
    job = wait(c, ws["id"], result["job"]["job_id"])
    assert job["state"] == "READY", job
    evidence = search(c, ws["id"])["evidence"][0]
    assert evidence["relative_path"] == "운영/정책.md" and "75일" in evidence["text"]
    assert (core.uploads.published / row["id"] / "운영/정책.md").read_bytes() == DATA
    assert not (core.uploads.staging / row["id"]).exists()
    assert put(c, row).status_code == 409
    assert c.delete(f"/api/rag/uploads/{row['id']}").status_code == 409
    assert c.delete(f"/api/rag/workspaces/{ws['id']}").json()["source_preserved"] is False
    assert not (core.uploads.published / row["id"]).exists()
    assert not core.db.one("SELECT id FROM upload_sessions WHERE id=?", (row["id"],))
    assert original.read_text() == "서버 원본"


@pytest.mark.parametrize(
    "path",
    [
        "../a.txt",
        "/a.txt",
        "a//b.txt",
        "a/./b.txt",
        "a\\b.txt",
        "%2e%2e/a.txt",
        "a\x00.txt",
        ".env",
        ".ssh/a.txt",
        "secrets/a.txt",
        "auth.json",
        "a:stream.txt",
        "node_modules/a.txt",
        "/".join(["d"] * 12) + "/a.txt",
        "script.py",
        "CON.txt",
        "NUL.md",
        "COM1.txt",
        "LPT¹.txt",
        "CONIN$.txt",
        "folder./a.txt",
        "folder /a.txt",
        'quote".txt',
        "wildcard?.txt",
        "wildcard*.txt",
        "pipe|.txt",
    ],
)
def test_unsafe_manifest_rejected(client, path):
    c, _, core = client
    r = begin(c, [{"path": path, "size": 1}])
    assert r.status_code in {400, 403}, r.text
    assert not core.db.all("SELECT * FROM upload_sessions")
    assert not list(core.uploads.staging.iterdir())


@pytest.mark.parametrize(
    "paths",
    [["A.txt", "a.txt"], ["café.txt", "cafe\u0301.txt"], ["a.txt", "a.txt/b.md"], ["a.txt/b.md", "a.txt"]],
)
def test_colliding_paths_rejected(client, paths):
    c, _, _ = client
    assert begin(c, [{"path": p, "size": 1} for p in paths]).json()["error_code"] == "DUPLICATE_PATH"


def test_size_count_and_storage_limits(client):
    c, _, core = client
    core.s.max_file_bytes = 4
    assert begin(c).status_code == 413
    core.s.max_file_bytes = 100
    core.s.max_total_bytes = 5
    assert begin(c, [{"path": "a.txt", "size": 3}, {"path": "b.txt", "size": 3}]).status_code == 413
    core.s.max_total_bytes = 100
    core.s.max_files = 2
    assert begin(c, [{"path": "a/b/c.txt", "size": 1}]).status_code == 413
    core.s.max_files = 100
    core.s.upload_storage_bytes = 5
    first = begin(c, [{"path": "a.txt", "size": 4}]).json()
    assert begin(c, [{"path": "b.txt", "size": 2}]).json()["error_code"] == "UPLOAD_STORAGE_FULL"
    assert c.delete(f"/api/rag/uploads/{first['id']}").status_code == 200
    assert begin(c, [{"path": "b.txt", "size": 2}]).status_code == 201


def test_mismatched_stream_and_disconnect_cleanup(client):
    c, _, core = client
    row = begin(c).json()
    assert put(c, row, data=b"short").status_code == 400
    assert put(c, row, data=iter([b"x" * (len(DATA) + 1)])).status_code == 413
    assert put(c, row, data=iter([b"x"])).status_code == 400
    assert not c.get(f"/api/rag/uploads/{row['id']}").json()["files"][0]["received"]
    assert not list((core.uploads.staging / row["id"]).iterdir())

    async def broken():
        yield b"x"
        raise ClientDisconnect()

    with pytest.raises(RagError, match="UPLOAD_INTERRUPTED"):
        asyncio.run(
            core.uploads.receive(row["id"], row["files"][0]["id"], SimpleNamespace(headers={}, stream=broken))
        )
    assert not list((core.uploads.staging / row["id"]).iterdir())
    assert put(c, row).status_code == 200


def test_expiry_cleanup_restart_and_incomplete_files(client):
    c, _, core = client
    row = begin(c).json()
    assert put(c, row).status_code == 200
    staged = core.uploads.staging / row["id"]
    (staged / "leftover.part").write_bytes(b"partial")
    # Reconstruct service, as on restart; acknowledged file remains available.
    core.uploads = UploadService(core)
    assert not (staged / "leftover.part").exists()
    assert c.get(f"/api/rag/uploads/{row['id']}").json()["files"][0]["received"]
    core.db.execute("UPDATE upload_sessions SET expires_at=? WHERE id=?", (time.time() - 1, row["id"]))
    assert c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).status_code == 410
    core.uploads.cleanup()
    assert not staged.exists()
    assert c.get(f"/api/rag/uploads/{row['id']}").status_code == 404


def test_no_anonymous_csrf_or_rebinding(client):
    c, _, core = client
    assert c.get("/api/rag/uploads/limits", headers={"Authorization": ""}).status_code == 401
    assert c.post("/api/rag/uploads", json={}, headers={"Authorization": ""}).status_code == 401
    row = begin(c).json()
    assert put(c, row, headers={"Authorization": ""}).status_code == 401
    assert put(c, row, headers={"Origin": "https://evil.example"}).status_code == 403
    wid = create(c, "")
    source = {"root_id": UPLOAD_ROOT, "relative_path": row["id"]}
    assert c.post("/api/rag/workspaces", json={"name": "rebound", **source}).status_code == 403
    assert c.post(f"/api/rag/workspaces/{wid}/sources", json=source).status_code == 403
    assert c.post("/api/rag/source-previews", json=source).status_code == 403
    assert c.get("/api/rag/source-roots/__uploads__/entries").status_code == 403
    assert core.db.one("SELECT version FROM schema_version")["version"] == 9


def test_manifest_over_json_limit_and_integrity(client):
    c, _, core = client
    files = [{"path": ("한글" * 40) + f"{i}.txt", "size": 1} for i in range(300)]
    assert len(json.dumps(files).encode()) > 65536
    response = begin(c, files)
    assert response.status_code == 201, response.text
    row = response.json()
    c.delete(f"/api/rag/uploads/{row['id']}")
    row = begin(c).json()
    assert put(c, row).status_code == 200
    (core.uploads.staging / row["id"] / row["files"][0]["id"]).write_bytes(b"tampered")
    response = c.post(f"/api/rag/uploads/{row['id']}/commit", json={})
    assert response.status_code == 409 and response.json()["error_code"] == "UPLOAD_INTEGRITY_FAILED"
    assert not c.get("/api/rag/workspaces").json()


def test_session_cookie_requires_csrf_for_file_transfer(client):
    from conftest import KEY

    c, _, _ = client
    row = begin(c).json()
    login = c.post("/api/rag/auth/login", json={"key": KEY}).json()
    headers = {"Authorization": "", "Origin": "http://localhost:8766"}
    assert put(c, row, headers=headers).status_code == 403
    headers["X-CSRF-Token"] = login["csrf"]
    assert put(c, row, headers=headers).status_code == 200


def test_full_queue_keeps_uploaded_workspace_and_can_retry(client, monkeypatch):
    c, _, core = client
    row = begin(c).json()
    assert put(c, row).status_code == 200
    real = core.ingestion.create

    def unavailable(*args, **kwargs):
        raise RagError("JOB_QUEUE_FULL", "대기 중인 작업이 많습니다.", 429)

    monkeypatch.setattr(core.ingestion, "create", unavailable)
    first = c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).json()
    assert first["index_error"] and not first["job"]
    monkeypatch.setattr(core.ingestion, "create", real)
    second = c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).json()
    assert second["workspace"]["id"] == first["workspace"]["id"] and second["job"]
    assert wait(c, second["workspace"]["id"], second["job"]["job_id"])["state"] == "READY"


def test_failed_publication_can_retry_without_duplicate_workspace(client, monkeypatch):
    c, _, core = client
    row = begin(c).json()
    assert put(c, row).status_code == 200
    execute = core.db.execute

    def fail(sql, args=()):
        if sql.startswith("UPDATE upload_sessions SET state='COMMITTED'"):
            raise RuntimeError("simulated failure")
        return execute(sql, args)

    monkeypatch.setattr(core.db, "execute", fail)
    with pytest.raises(RuntimeError, match="simulated failure"):
        c.post(f"/api/rag/uploads/{row['id']}/commit", json={})
    monkeypatch.setattr(core.db, "execute", execute)
    assert not c.get("/api/rag/workspaces").json()
    assert not (core.uploads.published / row["id"]).exists()
    assert c.post(f"/api/rag/uploads/{row['id']}/commit", json={}).status_code == 200
