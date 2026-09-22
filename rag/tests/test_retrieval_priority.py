"""Reserved retrieval admission and snapshot validation without real model calls."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_meeting import ready

from meetingbot_rag.sources import RagError


def block_query(monkeypatch, core, text):
    entered, release = threading.Event(), threading.Event()
    original = core.model.encode

    def encode(texts, query=False):
        if query and texts == [text]:
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Synthetic embedding was not released")
        return original(texts, query=query)

    monkeypatch.setattr(core.model, "encode", encode)
    return entered, release


def priority_search(service, *args):
    with service.priority_lane():
        return service.search(*args)


def test_priority_admission_and_snapshot_lock_are_available_during_shared_query(client, monkeypatch):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    entered, release = block_query(monkeypatch, core, "로그 보관 기간 SQ")
    with ThreadPoolExecutor(max_workers=2) as pool:
        shared = pool.submit(core.retrieval.search, wid, "로그 보관 기간 SQ", revision)
        try:
            assert entered.wait(timeout=2)
            with pytest.raises(RagError, match="SEARCH_BUSY"):
                core.retrieval.search(wid, "다른 일반 검색", revision)
            pq = pool.submit(priority_search, core.retrieval, wid, "운영 로그 보관 기간", revision)
            result = pq.result(timeout=2)
            assert result["status"] == "found" and result["evidence"]
            assert not shared.done()
        finally:
            release.set()
        assert shared.result(timeout=2)["status"] == "found"


def test_reserved_slot_is_bounded_and_does_not_consume_shared_capacity(client, monkeypatch):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    entered, release = block_query(monkeypatch, core, "로그 보관 기간 PQ")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pq = pool.submit(priority_search, core.retrieval, wid, "로그 보관 기간 PQ", revision)
        try:
            assert entered.wait(timeout=2)
            with core.retrieval.priority_lane(), pytest.raises(RagError, match="SEARCH_BUSY"):
                core.retrieval.search(wid, "다른 우선 검색", revision)
            assert core.retrieval.search(wid, "운영 로그 보관 기간", revision)["status"] == "found"
        finally:
            release.set()
        assert pq.result(timeout=2)["status"] == "found"


def test_priority_context_is_nested_thread_local_and_restored_after_error(client):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    service = core.retrieval
    service.gate.acquire()
    try:
        with service.priority_lane():
            with pytest.raises(ValueError), service.priority_lane():
                raise ValueError("Synthetic caller failure")
            assert service.search(wid, "로그 보관 기간", revision)["status"] == "found"
            with ThreadPoolExecutor(max_workers=1) as pool:
                normal = pool.submit(service.search, wid, "로그 보관 기간", revision)
                with pytest.raises(RagError, match="SEARCH_BUSY"):
                    normal.result(timeout=2)
        with pytest.raises(RagError, match="SEARCH_BUSY"):
            service.search(wid, "로그 보관 기간", revision)
    finally:
        service.gate.release()


@pytest.mark.parametrize("priority", [False, True])
def test_query_failure_releases_only_the_admitted_slot(client, monkeypatch, priority):
    _, _, core = client
    wid, revision = ready(client, approve=False)

    def fail(*_args, **_kwargs):
        raise RuntimeError("Synthetic embedding failure")

    monkeypatch.setattr(core.model, "encode", fail)
    invoke = priority_search if priority else lambda service, *args: service.search(*args)
    with pytest.raises(RuntimeError, match="Synthetic embedding failure"):
        invoke(core.retrieval, wid, "로그 보관 기간", revision)
    assert core.retrieval.gate.acquire(blocking=False)
    assert core.retrieval.priority_gate.acquire(blocking=False)
    core.retrieval.gate.release()
    core.retrieval.priority_gate.release()


@pytest.mark.parametrize("change", ["source", "workspace", "revision", "fingerprint"])
def test_revocation_during_embedding_never_returns_captured_evidence(client, monkeypatch, change):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    entered, release = block_query(monkeypatch, core, "로그 보관 기간")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(priority_search, core.retrieval, wid, "로그 보관 기간", revision)
        try:
            assert entered.wait(timeout=2)
            # Acquiring this lock from the other thread proves encoding does not own it.
            assert core.workspaces.locks[wid].acquire(timeout=1)
            try:
                if change == "source":
                    core.s.source_roots_file.write_text("roots: []")
                elif change == "workspace":
                    core.db.execute("UPDATE workspaces SET deleted=1 WHERE id=?", (wid,))
                elif change == "revision":
                    core.db.execute("UPDATE revisions SET state='FAILED' WHERE id=?", (revision,))
                else:
                    core.db.execute("UPDATE revisions SET fingerprint='changed' WHERE id=?", (revision,))
            finally:
                core.workspaces.locks[wid].release()
        finally:
            release.set()
        with pytest.raises(RagError) as error:
            pending.result(timeout=2)
        expected = {
            "source": {"SOURCE_ACCESS_REVOKED"},
            "workspace": {"NOT_FOUND"},
            "revision": {"REVISION_NOT_READY"},
            "fingerprint": {"REVISION_CHANGED"},
        }
        assert error.value.code in expected[change]


def test_late_access_revocation_after_vector_search_is_checked_again(client, monkeypatch):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    original = core.vectors.call

    def revoke_after_search(operation, *args):
        result = original(operation, *args)
        if operation == "search":
            core.s.source_roots_file.write_text("roots: []")
        return result

    monkeypatch.setattr(core.vectors, "call", revoke_after_search)
    with pytest.raises(RagError, match="SOURCE_ACCESS_REVOKED"):
        core.retrieval.search(wid, "로그 보관 기간", revision)


def test_deleted_keyword_snapshot_is_not_recreated_as_an_empty_database(client, monkeypatch):
    _, _, core = client
    wid, revision = ready(client, approve=False)
    path = core.revisions.path(wid, revision) / "keyword.sqlite"
    original = core.vectors.call

    def remove_after_search(operation, *args):
        result = original(operation, *args)
        if operation == "search":
            path.unlink()
            core.db.execute("UPDATE revisions SET state='FAILED' WHERE id=?", (revision,))
        return result

    monkeypatch.setattr(core.vectors, "call", remove_after_search)
    with pytest.raises(RagError, match="REVISION_NOT_READY"):
        core.retrieval.search(wid, "로그 보관 기간", revision)
    assert not path.exists()
