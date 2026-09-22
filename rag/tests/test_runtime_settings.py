import json
import threading
import time

import pytest
from conftest import KEY, FakeModel, ask
from fastapi.testclient import TestClient
from test_rag import create, index, search, wait

from meetingbot_rag.app import create_app
from meetingbot_rag.process_lock import acquire_process_lock


def save(c, **values):
    current = c.get("/api/rag/settings").json()
    body = {key: current[key] for key in ("chunk_tokens", "overlap_tokens", "top_k")}
    body.update(expected_version=current["version"], **values)
    response = c.put("/api/rag/settings", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_settings_auth_csrf_validation_and_conflict(client):
    c, _, _ = client
    original = c.get("/api/rag/settings").json()
    assert original["version"] == 0 and original["chunk_tokens"] == 320
    assert c.get("/api/rag/settings", headers={"Authorization": ""}).status_code == 401
    body = {"expected_version": 0, "chunk_tokens": 64, "overlap_tokens": 8, "top_k": 2}
    assert c.put("/api/rag/settings", json=body, headers={"Authorization": ""}).status_code == 401
    login = c.post("/api/rag/auth/login", json={"key": KEY}).json()
    assert c.put("/api/rag/settings", json=body, headers={"Authorization": ""}).status_code == 403
    for invalid in (
        {"chunk_tokens": 31},
        {"chunk_tokens": 401},
        {"overlap_tokens": -1},
        {"overlap_tokens": 64},
        {"top_k": 0},
        {"top_k": 13},
        {"chunk_tokens": "64"},
        {"top_k": True},
        {"download_url": "https://example.invalid"},
    ):
        assert c.put("/api/rag/settings", json={**body, **invalid}).status_code == 422
    assert c.get("/api/rag/settings").json() == original
    response = c.put(
        "/api/rag/settings",
        json=body,
        headers={
            "Authorization": "",
            "Origin": "http://localhost:8766",
            "X-CSRF-Token": login["csrf"],
        },
    )
    assert response.status_code == 200 and response.json()["version"] == 1
    conflict = c.put("/api/rag/settings", json={**body, "top_k": 3})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "SETTINGS_VERSION_CONFLICT"
    assert c.get("/api/rag/settings").json()["top_k"] == 2


def test_settings_persist_across_service_restarts(env):
    settings, _ = env
    for restart in range(2):
        with TestClient(create_app(settings, FakeModel()), headers={"Authorization": "Bearer " + KEY}) as c:
            if restart == 0:
                saved = save(c, chunk_tokens=96, overlap_tokens=12, top_k=9)
            else:
                assert c.get("/api/rag/settings").json() == saved


def test_new_chunking_requires_rebuild_and_changes_chunk_count(client):
    c, root, core = client
    (root / "policy.txt").write_text("로그 보관 기간은 90일입니다. " * 150)
    wid = create(c, "")
    initial = index(c, wid)
    assert initial["state"] == "READY"
    count = initial["result"]["chunks"]
    changed = save(c, chunk_tokens=64, overlap_tokens=8)
    assert changed["reindex_required"]
    workspace = changed["workspaces"][0]
    assert workspace["workspace_id"] == wid and workspace["requires_reindex"]
    assert workspace["chunk_count"] == count
    assert search(c, wid)["revision_id"] == initial["revision_id"]
    rebuilt = index(c, wid)
    assert rebuilt["state"] == "READY"
    assert rebuilt["result"]["reused_documents"] == 0
    assert rebuilt["result"]["chunks"] > count
    assert rebuilt["result"]["config"]["chunk_tokens"] == 64
    assert not c.get("/api/rag/settings").json()["reindex_required"]
    assert index(c, wid)["result"]["reused_documents"] == 1
    assert not save(c, top_k=3)["reindex_required"]
    changed_overlap = save(c, overlap_tokens=24)
    assert changed_overlap["reindex_required"]
    overlap_index = index(c, wid)
    assert overlap_index["result"]["reused_documents"] == 0
    assert overlap_index["result"]["chunks"] > rebuilt["result"]["chunks"]
    assert not c.get("/api/rag/settings").json()["reindex_required"]


def test_inflight_index_keeps_captured_chunk_configuration(client):
    c, root, core = client
    (root / "policy.txt").write_text("로그 보관 기간은 90일입니다. " * 30)
    wid = create(c, "")
    save(c, chunk_tokens=64, overlap_tokens=8)
    entered, release = threading.Event(), threading.Event()
    real_parse = core.parser.parse

    def blocked(*args):
        entered.set()
        assert release.wait(5)
        return real_parse(*args)

    core.parser.parse = blocked
    job = c.post(f"/api/rag/workspaces/{wid}/index-jobs", json={}).json()
    try:
        assert entered.wait(3)
        assert save(c, chunk_tokens=128, overlap_tokens=16)["workspaces"][0]["indexing"]
    finally:
        release.set()
    complete = wait(c, wid, job["job_id"])
    assert complete["state"] == "READY"
    assert complete["result"]["config"]["chunk_tokens"] == 64
    revision = core.db.one("SELECT config,fingerprint FROM revisions WHERE id=?", (job["revision_id"],))
    versions = core.db.all("SELECT chunks,fingerprint FROM document_versions WHERE workspace_id=?", (wid,))
    assert json.loads(revision["config"])["overlap_tokens"] == 8
    assert versions[0]["fingerprint"] == revision["fingerprint"]
    assert all(core.model.tokens(chunk["text"]) <= 64 for chunk in json.loads(versions[0]["chunks"]))
    assert c.get("/api/rag/settings").json()["reindex_required"]
    rebuilt = index(c, wid)
    assert rebuilt["result"]["config"]["chunk_tokens"] == 128
    assert rebuilt["result"]["chunks"] < complete["result"]["chunks"]


def test_retrieval_default_updates_immediately_for_search_and_questions(client):
    c, root, _ = client
    for i in range(12):
        (root / f"policy-{i}.txt").write_text(f"로그 보관 기간은 {i + 30}일입니다.")
    wid = create(c, "")
    assert index(c, wid)["state"] == "READY"
    assert len(search(c, wid)["evidence"]) == 6
    save(c, top_k=2)
    assert len(search(c, wid)["evidence"]) == 2
    assert len(search(c, wid, top_k=12)["evidence"]) == 2
    changed = save(c, top_k=12)
    assert len(search(c, wid)["evidence"]) == 12
    assert len(search(c, wid, top_k=1)["evidence"]) == 1
    answer = ask(c, f"/api/rag/workspaces/{wid}/questions", json={"query": "로그 보관 기간"})
    assert len(answer["evidence"]) == 12
    assert answer["retrieval_settings_version"] == changed["version"]
    assert c.post(f"/api/rag/workspaces/{wid}/search", json={"query": "로그", "top_k": 13}).status_code == 422


def test_embedding_install_is_authenticated_background_and_retryable(env):
    settings, _ = env
    entered, release = threading.Event(), threading.Event()

    class DownloadModel(FakeModel):
        state = "NOT_READY"
        error = "MODEL_DOWNLOAD_REQUIRED"
        downloads = 0

        def load(self, download=False):
            if not download:
                return
            self.downloads += 1
            self.state = "DOWNLOADING"
            entered.set()
            assert release.wait(5)
            if self.downloads == 1:
                self.state, self.error = "NOT_READY", "MODEL_LOAD_FAILED"
                raise RuntimeError("private download error must never be shown")
            self.state, self.error = "READY", None

        def health(self):
            return {**super().health(), "state": self.state, "error_code": self.error}

    model = DownloadModel()
    with TestClient(create_app(settings, model), headers={"Authorization": "Bearer " + KEY}) as c:
        assert c.get("/api/rag/embedding", headers={"Authorization": ""}).status_code == 401
        assert c.post("/api/rag/embedding/install", headers={"Authorization": ""}).status_code == 401
        assert c.get("/api/rag/embedding").json()["state"] == "NOT_READY"
        response = c.post("/api/rag/embedding/install")
        assert response.status_code == 202 and response.json()["state"] == "DOWNLOADING"
        try:
            assert entered.wait(3)
            assert c.post("/api/rag/embedding/install").status_code == 202
            assert c.get("/api/rag/embedding").json()["installing"]
            assert model.downloads == 1
        finally:
            release.set()
        for _ in range(100):
            status = c.get("/api/rag/embedding").json()
            if not status["installing"]:
                break
            time.sleep(0.01)
        assert status["state"] == "NOT_READY" and status["error_code"] == "MODEL_LOAD_FAILED"
        assert "private" not in json.dumps(status)
        assert c.post("/api/rag/embedding/install").status_code == 202
        for _ in range(100):
            status = c.get("/api/rag/embedding").json()
            if not status["installing"]:
                break
            time.sleep(0.01)
        assert status["state"] == "READY" and model.downloads == 2
        assert c.post("/api/rag/embedding/install").json()["state"] == "READY"
        assert model.downloads == 2


def test_process_lock_excludes_second_service_and_releases(tmp_path):
    path = tmp_path / "service.lock"
    lock = acquire_process_lock(path)
    try:
        with pytest.raises(RuntimeError, match="Only one RAG"):
            acquire_process_lock(path)
    finally:
        lock.close()
    acquire_process_lock(path).close()


def test_windows_alternate_data_stream_paths_are_denied(client):
    c, _, _ = client
    assert (
        c.get("/api/rag/source-roots/docs/entries", params={"relative_path": "file.txt:stream"}).status_code
        == 403
    )
