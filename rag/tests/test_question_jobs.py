"""Async admission, shared capacity, crash recovery and ownership without a real LLM."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from conftest import KEY, FakeModel, wait_question
from fastapi.testclient import TestClient
from test_meeting import ready
from test_meeting_jobs import label, row, step, submit
from test_meeting_jobs import queued as queued

from meetingbot_rag.answers import AnswerService
from meetingbot_rag.app import create_app
from meetingbot_rag.question_jobs import QuestionJobs
from meetingbot_rag.sources import RagError


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Background condition did not become true")


def result(wid, query, **_):
    return {"workspace_id": wid, "query": query, "status": "answered", "answer": query,
            "evidence": [], "citations": [], "timings_ms": {}}


def submit_question(c, wid, query="질문", **kwargs):
    response = c.post(f"/api/rag/workspaces/{wid}/questions", json={"query": query}, **kwargs)
    assert response.status_code == 202, response.text
    return response


def test_requests_return_before_model_finishes_and_only_three_run(client, monkeypatch):
    c, _, core = client
    wid = core.workspaces.create("자료", "")["id"]
    release, three_started = threading.Event(), threading.Event()
    guard = threading.Lock()
    active = peak = 0
    calls = []

    def slow(wid, query, **kwargs):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
            calls.append(query)
            if active == 3:
                three_started.set()
        try:
            assert release.wait(5)
            return result(wid, query)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(c.app.state.answer, "answer", slow)
    accounts = [c.app.state.access.issue_key(f"사용자 {i}", "visitor") for i in range(8)]
    try:
        started = time.monotonic()
        responses = [submit_question(c, wid, str(i), headers={"Authorization": "Bearer " + a["key"]})
                     for i, a in enumerate(accounts)]
        assert time.monotonic() - started < 2
        assert three_started.wait(2)
        states = [json.loads(r["result"])["status"] for r in core.db.all("SELECT result FROM query_runs")]
        assert states.count("processing") == 3 and states.count("queued") == 5
        assert peak == 3 and len(calls) == 3
        # API reads stay responsive, and another user cannot read a queued message.
        assert c.get("/api/rag/history").status_code == 200
        rid = responses[-1].json()["request_id"]
        assert c.get(f"/api/rag/history/{rid}", headers={"Authorization": "Bearer " + accounts[0]["key"]}).status_code == 404
    finally:
        release.set()
    wait_until(lambda: all(json.loads(r["result"])["status"] == "answered"
                           for r in core.db.all("SELECT result FROM query_runs")))
    assert len(calls) == 8 and len(set(calls)) == 8 and peak == 3


def test_real_answer_path_allows_three_llm_calls_and_requeues_local_search(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)
    release, entered = threading.Event(), threading.Event()
    guard = threading.Lock()
    count = peak = 0

    class LLM:
        def invoke(self, messages):
            nonlocal count, peak
            with guard:
                count += 1
                peak = max(peak, count)
                if count == 3:
                    entered.set()
            try:
                assert release.wait(5)
                evidence = json.loads(messages[-1][1])["evidence"]
                return SimpleNamespace(content=json.dumps({"status": "answered", "answer": "90일",
                                                            "citations": [evidence[0]["evidence_id"]]}))
            finally:
                with guard:
                    count -= 1

    monkeypatch.setattr(c.app.state.answer.factory, "create", lambda *_: LLM())
    try:
        responses = [submit_question(c, wid, "운영 로그 보관 기간") for _ in range(5)]
        assert entered.wait(3)
    finally:
        release.set()
    assert all(wait_question(c, response)["status"] == "answered" for response in responses)
    assert peak == 3


def test_idempotency_is_atomic_account_scoped_and_conflicts_are_rejected(client, monkeypatch):
    c, _, core = client
    wid = core.workspaces.create("자료", "")["id"]
    calls = []
    monkeypatch.setattr(c.app.state.answer, "answer", lambda w, query, **kw: (calls.append(query) or result(w, query)))
    headers = {"Idempotency-Key": "repeat-1"}
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: submit_question(c, wid, headers=headers), range(6)))
    ids = {response.json()["request_id"] for response in responses}
    assert len(ids) == 1
    wait_question(c, responses[0])
    assert calls == ["질문"]
    conflict = c.post(f"/api/rag/workspaces/{wid}/questions", json={"query": "다른 질문"}, headers=headers)
    assert conflict.status_code == 409
    other = c.app.state.access.issue_key("다른 사용자", "visitor")
    second = submit_question(c, wid, headers={**headers, "Authorization": "Bearer " + other["key"]})
    assert second.json()["request_id"] not in ids
    detail = c.get(f"/api/rag/history/{responses[0].json()['request_id']}").json()
    assert "input" not in detail and "idempotency_key" not in detail


def test_restart_recovers_queued_and_inflight_messages(env, monkeypatch):
    settings, _ = env
    with TestClient(create_app(settings, FakeModel()), headers={"Authorization": "Bearer " + KEY}) as c:
        core = c.app.state.core
        wid = core.workspaces.create("자료", "")["id"]
        c.app.state.question_jobs.close()
        responses = [submit_question(c, wid, str(i)) for i in range(3)]
        core.db.execute("UPDATE query_runs SET result=json_set(result,'$.status','processing') WHERE id=?",
                        (responses[0].json()["request_id"],))
    # Reopen the same on-disk DB via the real app lifecycle; no old worker or DB connection survives.
    calls = []
    monkeypatch.setattr(AnswerService, "answer", lambda self, w, query, **kw: (calls.append(query) or result(w, query)))
    with TestClient(create_app(settings, FakeModel()), headers={"Authorization": "Bearer " + KEY}) as c:
        assert all(wait_question(c, response)["status"] == "answered" for response in responses)
    assert sorted(calls) == ["0", "1", "2"]


def test_accepts_requests_while_loading_but_starts_them_only_after_model_ready(env, monkeypatch):
    settings, _ = env
    release, loading = threading.Event(), threading.Event()
    calls = []

    class SlowModel(FakeModel):
        state = "LOADING"

        def load(self):
            loading.set()
            assert release.wait(5)
            self.state = "READY"

    model = SlowModel()
    def answer(self, wid, query, **kwargs):
        assert model.state == "READY"
        calls.append(query)
        return result(wid, query)
    monkeypatch.setattr(AnswerService, "answer", answer)
    with TestClient(create_app(settings, model), headers={"Authorization": "Bearer " + KEY}) as c:
        try:
            assert loading.wait(2)
            wid = c.app.state.core.workspaces.create("준비 중인 자료", "")["id"]
            response = submit_question(c, wid)
            saved = c.get(f"/api/rag/history/{response.json()['request_id']}").json()
            assert saved["result"]["status"] == "queued" and not calls
        finally:
            release.set()
        assert wait_question(c, response)["status"] == "answered"
    assert calls == ["질문"]


def test_busy_search_and_failed_model_do_not_lose_or_stall_queue(client, monkeypatch):
    c, _, core = client
    wid = core.workspaces.create("자료", "")["id"]
    calls = {}

    def compute(wid, query, **kwargs):
        calls[query] = calls.get(query, 0) + 1
        if query == "busy" and calls[query] == 1:
            raise RagError("SEARCH_BUSY", status=429)
        if query == "bad":
            raise RuntimeError("private error")
        return result(wid, query)

    monkeypatch.setattr(c.app.state.answer, "answer", compute)
    responses = [submit_question(c, wid, query) for query in ("bad", "busy", "good")]
    answers = [wait_question(c, response) for response in responses]
    assert [a["status"] for a in answers] == ["failed", "answered", "answered"]
    assert calls == {"bad": 1, "busy": 2, "good": 1}
    assert "private error" not in json.dumps(answers)


def test_revocation_and_deletion_before_execution_prevent_work(client, monkeypatch):
    c, _, core = client
    c.app.state.question_jobs.close()
    wid = core.workspaces.create("자료", "")["id"]
    other = core.workspaces.create("삭제 자료", "")["id"]
    account = c.app.state.access.issue_key("요청자", "visitor")
    response = submit_question(c, wid, headers={"Authorization": "Bearer " + account["key"]})
    deleted = submit_question(c, other)
    c.app.state.access.revoke(account["id"])
    core.delete(other)
    calls = []
    monkeypatch.setattr(c.app.state.answer, "answer", lambda *a, **kw: calls.append(a))
    service = QuestionJobs(core, c.app.state.answer, c.app.state.query_history, c.app.state.access)
    c.app.state.question_jobs = service
    service.start()
    rid = response.json()["request_id"]
    wait_until(lambda: json.loads(core.db.one("SELECT result FROM query_runs WHERE id=?", (rid,))["result"])["status"] == "failed")
    assert not calls
    assert core.db.one("SELECT id FROM query_runs WHERE id=?", (deleted.json()["request_id"],)) is None
    assert c.get(f"/api/rag/history/{rid}?scope=all").json()["result"]["reason"] == "AUTH_REQUIRED"


def test_consent_is_checked_when_dequeued(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)
    gate = c.app.state.answer.factory.gate
    for _ in range(3):
        gate.acquire()
    calls = []
    monkeypatch.setattr(c.app.state.answer.factory, "create", lambda *a: calls.append(a))
    try:
        response = submit_question(c, wid, "운영 로그 보관 기간")
        assert response.json()["status"] == "queued"
        c.patch(f"/api/rag/workspaces/{wid}", json={"external_llm_approved": False})
    finally:
        for _ in range(3):
            gate.release()
    assert wait_question(c, response)["reason"] == "EXTERNAL_LLM_NOT_APPROVED"
    assert not calls


def test_meeting_classification_and_both_generation_lanes_share_question_cap(queued, monkeypatch):
    c, core, service, wid, revision = queued
    release, entered = threading.Event(), threading.Event()
    started = []

    def slow(wid, query, **kwargs):
        started.append(query)
        if len(started) == 3:
            entered.set()
        assert release.wait(5)
        return result(wid, query)

    monkeypatch.setattr(c.app.state.answer, "answer", slow)
    meeting_calls = []
    service.classifier.classify = lambda *a, **kw: (meeting_calls.append("classify") or
                                                   SimpleNamespace(model_dump=lambda: label(1)))
    def generate(wid, body, *args, **kwargs):
        meeting_calls.append("generate")
        return {"status": "insufficient_evidence"}
    service.meeting.generate_classified = generate
    jobs = [submit(c, wid, revision, index=i) for i in range(3)]
    for job in jobs[1:]:
        core.db.execute("UPDATE meeting_jobs SET stage='generate',queue_class='PQ',score=4,classification=?,"
                        "checkpoint='{}' WHERE id=?", (json.dumps(label(4)), job["id"]))
    try:
        questions = [submit_question(c, wid, str(i)) for i in range(3)]
        assert entered.wait(2)
        step(service)
        assert meeting_calls == []
        assert all(row(core, job)["state"] == "QUEUED" for job in jobs)
        assert all(row(core, job)["attempts"] == 0 for job in jobs)
    finally:
        release.set()
    for response in questions:
        wait_question(c, response)
    # Make the scheduler's deferred jobs eligible without timing sleeps.
    core.db.execute("UPDATE meeting_jobs SET available_at=0")
    step(service)
    assert sorted(meeting_calls) == ["classify", "generate", "generate"]
    assert all(row(core, job)["state"] == "COMPLETED" for job in jobs)
