"""Durable admission, priority dispatch, cancellation and failure contracts."""

import json
import threading
import time
from types import SimpleNamespace

import pytest
from test_meeting import model, ready, request

from meetingbot_rag.db import dumps
from meetingbot_rag.meeting_jobs import MeetingJobs


@pytest.fixture
def queued(client, monkeypatch):
    c, _, core = client
    wid, revision = ready(client)
    service = c.app.state.meeting_jobs
    service.stop.set()
    service.wake.set()
    service.thread.join(timeout=2)
    c.app.state.access.owner("session-1", "superadmin")
    response = c.post(
        f"/api/rag/workspaces/{wid}/meeting/sessions/session-1/subscription",
        json={"enabled": True, "revision_id": revision},
    )
    assert response.status_code == 200, response.text
    model(monkeypatch, c)
    yield c, core, service, wid, revision


def label(score):
    return {
        "score": score,
        "classification_state": "resolved" if score else "needs_clarification",
        "scope": "in_scope" if score and score >= 3 else "out_of_scope" if score else "uncertain",
        "speech_act": "topic"
        if score == 3
        else "factual_claim"
        if score == 4
        else "request"
        if score == 5
        else "filler"
        if score == 1
        else "social",
        "addressed_to_ai": score == 5,
        "intent": "fact_check" if score == 4 else "context" if score and score >= 3 else "none",
        "keywords": ["운영 로그"] if score and score >= 3 else [],
        "query": "운영서버 로그 보관 기간" if score and score >= 3 else "",
        "claim": "운영서버 로그 기록이 45일 동안 서버에 남아요." if score == 4 else "",
        "reason_code": "TEST_CLASSIFICATION",
        "action_supported": True,
    }


def classify_as(service, score):
    service.classifier.classify = lambda *a, **k: SimpleNamespace(model_dump=lambda: label(score))


def submit(c, wid, revision, index=1, origin="live", **extra):
    body = request()
    body["utterance"]["utterance_id"] = f"utterance-{index}"
    body.update(revision_id=revision, source_key=f"source-{index}", origin=origin)
    body.update(extra)
    response = c.post(f"/api/rag/workspaces/{wid}/meeting/jobs", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def row(core, job):
    return core.db.one("SELECT * FROM meeting_jobs WHERE id=?", (job["id"],))


def step(service):
    service.tick()
    for future in list(service.running.values()):
        future.result(timeout=5)


@pytest.mark.parametrize("score", [1, 2])
def test_low_scores_are_durable_without_retrieval(queued, score, monkeypatch):
    c, core, service, wid, revision = queued
    classify_as(service, score)
    monkeypatch.setattr(service.meeting, "retrieve_classified", lambda *a: pytest.fail("No low-score RAG"))
    job = submit(c, wid, revision)
    step(service)
    saved = row(core, job)
    assert saved["score"] == score and saved["state"] == "COMPLETED" and saved["text"]
    assert json.loads(saved["classification"])["score"] == score
    response = c.get(f"/api/rag/workspaces/{wid}/meeting/jobs", params={"session_id": "session-1"})
    assert response.status_code == 200 and response.json()["jobs"][0]["score"] == score


@pytest.mark.parametrize("score", [1, 2, 3])
def test_non_action_classification_cannot_report_unsupported_action(queued, score):
    c, core, service, wid, revision = queued
    payload = {**label(score), "action_supported": False}
    service.classifier.classify = lambda *a, **k: SimpleNamespace(model_dump=lambda: payload)
    job = submit(c, wid, revision)
    step(service)
    if score <= 2:
        assert json.loads(row(core, job)["result"])["status"] == "suppressed"
    else:
        assert row(core, job)["queue_class"] == "SQ" and row(core, job)["stage"] == "retrieve"


@pytest.mark.parametrize("score,queue", [(3, "SQ"), (4, "PQ"), (5, "PQ")])
def test_score_routes_and_uses_one_generation_after_filter(queued, score, queue):
    c, core, service, wid, revision = queued
    classify_as(service, score)
    job = submit(c, wid, revision)
    step(service)
    assert row(core, job)["queue_class"] == queue
    step(service)
    assert row(core, job)["checkpoint"]
    step(service)
    saved = row(core, job)
    assert saved["state"] == "COMPLETED", saved
    result = json.loads(saved["result"])
    assert result["status"] == "popup" and result["evidence"]


def test_idempotency_does_not_reset_deadline_and_edits_supersede(queued):
    c, core, service, wid, revision = queued
    job = submit(c, wid, revision)
    again = submit(c, wid, revision)
    assert again["id"] == job["id"] and again["deadline_at"] == job["deadline_at"]
    edited = submit(c, wid, revision, source_key="edited-source")
    assert edited["id"] != job["id"] and row(core, job)["state"] == "SUPERSEDED"


def test_deadline_watchdog_runs_while_classifier_is_blocked(queued):
    c, core, service, wid, revision = queued
    release = threading.Event()
    entered = threading.Event()

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return SimpleNamespace(model_dump=lambda: label(4))

    service.classifier.classify = blocked
    job = submit(c, wid, revision)
    service.tick()
    assert entered.wait(1)
    try:
        service.clock = lambda: job["deadline_at"] + 1
        service.tick()
        assert row(core, job)["deadline_missed"] == 1
        assert row(core, job)["state"] == "CLASSIFYING"
    finally:
        release.set()
        for future in service.running.values():
            future.result(timeout=3)


def test_uncertain_scope_is_not_dropped_as_two(queued):
    c, core, service, wid, revision = queued
    classify_as(service, None)
    job = submit(c, wid, revision)
    step(service)
    saved = row(core, job)
    assert saved["state"] == "AWAITING_CONTEXT" and saved["score"] is None
    service.clock = lambda: saved["available_at"] + 0.01
    step(service)
    assert json.loads(row(core, job)["result"])["status"] == "needs_clarification"


def test_explicit_cancel_fences_inflight_and_is_idempotent(queued):
    c, core, service, wid, revision = queued
    job = submit(c, wid, revision)
    core.db.execute("UPDATE meeting_jobs SET state='RUNNING',lease_token='old' WHERE id=?", (job["id"],))
    old = row(core, job)
    url = f"/api/rag/workspaces/{wid}/meeting/sessions/session-1/cancel"
    assert c.post(url, json={"delete": False}).status_code == 200
    assert service._update(old, state="COMPLETED", result="{}") == 0
    assert c.post(url, json={"delete": True}).status_code == 200
    assert c.post(url, json={"delete": True}).status_code == 200
    assert row(core, job) is None


@pytest.mark.parametrize("route", ["cancel", "subscription"])
def test_stopping_subscription_preserves_completed_archive(queued, route):
    c, core, service, wid, revision = queued
    classify_as(service, 4)
    completed = submit(c, wid, revision)
    for _ in range(3):
        step(service)
    saved = row(core, completed)
    pending = submit(c, wid, revision, index=2)
    body = {"delete": False} if route == "cancel" else {"enabled": False, "revision_id": revision}
    response = c.post(f"/api/rag/workspaces/{wid}/meeting/sessions/session-1/{route}", json=body)
    assert response.status_code == 200
    assert row(core, pending)["state"] == "CANCELLED"
    assert row(core, completed)["state"] == "COMPLETED"
    assert row(core, completed)["result"] == saved["result"]
    page = c.get(f"/api/rag/workspaces/{wid}/meeting/jobs", params={"session_id": "session-1"}).json()
    assert page["total"] == 1 and page["jobs"][0]["result"]["status"] == "popup"


def test_internal_cleanup_after_workspace_deletion_is_idempotent(queued):
    c, _, _, wid, _ = queued
    headers = {"X-Meeting-Subscription": "1",
               "X-Meeting-Bridge-Secret": c.app.state.access.service_secret("meeting-subscription")}
    no_grant = f"/api/rag/workspaces/{wid}/meeting/sessions/unregistered/cancel"
    assert c.post(no_grant, json={}, headers=headers).status_code == 409
    assert c.delete(f"/api/rag/workspaces/{wid}").status_code == 200
    url = f"/api/rag/workspaces/{wid}/meeting/sessions/session-1/cancel"
    assert c.post(url, json={}, headers=headers).status_code == 200
    assert c.post(url, json={"delete": True}, headers=headers).status_code == 200
    assert c.post(url, json={}).status_code == 409


def test_restart_recovers_checkpoint_and_replaces_lease(queued):
    c, core, service, wid, revision = queued
    job = submit(c, wid, revision)
    core.db.execute(
        "UPDATE meeting_jobs SET state='RUNNING',stage='generate',checkpoint='{}',lease_token='old' "
        "WHERE id=?",
        (job["id"],),
    )
    restarted = MeetingJobs(
        core, c.app.state.answer, c.app.state.meeting, c.app.state.access, classifier=service.classifier
    )
    try:
        saved = row(core, job)
        assert saved["state"] == "QUEUED" and saved["lease_token"] is None and saved["checkpoint"] == "{}"
    finally:
        restarted.close()


def test_file_jobs_cannot_use_live_reserved_lane(queued):
    c, core, service, wid, revision = queued
    classify_as(service, 4)
    submit(c, wid, revision, origin="file")
    step(service)
    service.tick()
    assert "priority" not in service.running and "shared" in service.running
    for future in service.running.values():
        future.result(timeout=3)


def test_pq_protection_pauses_sq_and_earlier_four_precedes_new_five(queued):
    c, core, service, wid, revision = queued
    sq = submit(c, wid, revision, index=1)
    pq4 = submit(c, wid, revision, index=2)
    pq5 = submit(c, wid, revision, index=3)
    for job, score, queue in ((sq, 3, "SQ"), (pq4, 4, "PQ"), (pq5, 5, "PQ")):
        core.db.execute(
            "UPDATE meeting_jobs SET score=?,queue_class=?,classification=?,stage='retrieve' WHERE id=?",
            (score, queue, dumps(label(score)), job["id"]),
        )
    now = time.time()
    core.db.execute(
        "UPDATE meeting_jobs SET deadline_at=?,received_at=? WHERE id=?", (now + 1, now - 19, pq4["id"])
    )
    jobs = [row(core, job) for job in (sq, pq4, pq5)]
    assert service._mode(wid, jobs, now) == "PQ_ONLY"
    assert service._pick(jobs[1:], "priority")["id"] == pq4["id"]
    # Busy PQ slots still trigger pause instead of launching SQ in shared capacity.
    service.tick()
    assert row(core, sq)["state"] == "PAUSED"
    for future in service.running.values():
        future.result(timeout=3)


def test_admission_has_no_eight_item_silent_drop(queued):
    c, core, _, wid, revision = queued
    jobs = [submit(c, wid, revision, index=i) for i in range(12)]
    assert all(row(core, job)["state"] == "QUEUED" for job in jobs)


def test_policy_permissions_threshold_validation_and_scope_reclassification(queued):
    c, core, service, wid, revision = queued
    classify_as(service, 2)
    job = submit(c, wid, revision)
    step(service)
    url = f"/api/rag/workspaces/{wid}/meeting/policy"
    current = c.get(url).json()
    body = {k: v for k, v in current.items() if k != "version"}
    assert c.put(url, json={**body, "expected_version": 0, "protect_ratio": 0.1}).status_code == 422
    body["scope_profile"]["description"] = "우리 서비스 운영 로그와 배포 관리"
    assert c.put(url, json={**body, "expected_version": 0}).status_code == 200
    saved = row(core, job)
    assert saved["stage"] == "classify" and saved["score"] is None
    assert saved["deadline_at"] == job["deadline_at"]
    assert c.put(url, json={**body, "expected_version": 0}).status_code == 409


@pytest.mark.parametrize("role", ["visitor", "admin", "superadmin"])
def test_other_accounts_cannot_view_or_subscribe_to_a_recording(queued, role):
    c, _, service, wid, revision = queued
    key = c.app.state.access.issue_key("other account", role)
    headers = {"Authorization": "Bearer " + key["key"]}
    base = f"/api/rag/workspaces/{wid}/meeting"
    assert c.get(base + "/jobs?session_id=session-1", headers=headers).status_code == 404
    assert c.post(base + "/sessions/session-1/cancel", headers=headers, json={}).status_code == 404
    assert (
        c.post(
            base + "/sessions/session-1/subscription",
            headers=headers,
            json={"enabled": True, "revision_id": revision},
        ).status_code
        == 404
    )
    assert (
        c.post(
            base + "/sessions/session-1/cancel", headers={**headers, "X-Meeting-Subscription": "1"}, json={}
        ).status_code
        == 403
    )
    policy = service.policies.get(wid)
    if role == "visitor":
        assert (
            c.put(
                base + "/policy",
                headers=headers,
                json={**{k: v for k, v in policy.items() if k != "version"}, "expected_version": 0},
            ).status_code
            == 403
        )


def test_classifier_error_is_failed_not_smalltalk(queued):
    c, core, service, wid, revision = queued

    def broken(*args, **kwargs):
        raise ValueError("synthetic invalid output")

    service.classifier.classify = broken
    job = submit(c, wid, revision)
    step(service)
    saved = row(core, job)
    assert saved["state"] == "RETRY_WAIT" and saved["score"] is None and saved["result"] is None
    service.clock = lambda: saved["available_at"] + 0.1
    step(service)
    assert row(core, job)["state"] == "FAILED"


def test_older_revision_and_generation_cannot_replace_latest(queued):
    c, core, _, wid, revision = queued
    body = request()
    body["utterance"]["revision"] = 2
    body.update(revision_id=revision, source_key="latest", source_generation=8)
    base = f"/api/rag/workspaces/{wid}/meeting"
    job = c.post(base + "/jobs", json=body).json()
    body["utterance"]["revision"] = 1
    body["source_key"] = "older"
    assert c.post(base + "/jobs", json=body).status_code == 409
    body["utterance"]["revision"] = 2
    body["source_generation"] = 7
    assert c.post(base + "/jobs", json=body).status_code == 409
    assert row(core, job)["state"] == "QUEUED"
    assert (
        c.post(
            base + "/sessions/session-1/sync", json={"utterance_ids": ["utterance-1"], "generation": 8}
        ).status_code
        == 200
    )
    assert (
        c.post(base + "/sessions/session-1/sync", json={"utterance_ids": [], "generation": 7}).status_code
        == 409
    )
    assert row(core, job)["state"] == "QUEUED"


def test_completion_between_watchdog_ticks_keeps_deadline_miss(queued):
    c, core, service, wid, revision = queued
    job = submit(c, wid, revision)
    core.db.execute(
        "UPDATE meeting_jobs SET state='RUNNING',stage='generate',queue_class='PQ',"
        "lease_token='test' WHERE id=?",
        (job["id"],),
    )
    saved = row(core, job)
    service.clock = lambda: saved["deadline_at"] + 0.001
    service._finish(saved, service._result(saved, "insufficient_evidence", "NO_EVIDENCE"))
    assert row(core, job)["deadline_missed"] == 1


def test_retry_resets_stale_checkpoint_and_model_identity(queued):
    c, core, service, wid, revision = queued
    job = submit(c, wid, revision)
    core.db.execute(
        "UPDATE meeting_jobs SET state='FAILED',stage='generate',provider_id='old',checkpoint='{}' "
        "WHERE id=?",
        (job["id"],),
    )
    result = c.post(
        f"/api/rag/workspaces/{wid}/meeting/jobs/{job['id']}/retry", json={"session_id": "session-1"}
    )
    assert result.status_code == 200
    saved = row(core, job)
    assert saved["stage"] == "classify" and saved["checkpoint"] is None and saved["provider_id"] != "old"
    assert saved["deadline_at"] == job["deadline_at"]


def test_pagination_anchor_and_superseded_cursor_do_not_lose_history(queued):
    c, core, _, wid, revision = queued
    ids = {submit(c, wid, revision, index=i)["id"] for i in range(4)}
    base = f"/api/rag/workspaces/{wid}/meeting/jobs?session_id=session-1&limit=2"
    first = c.get(base).json()
    second = c.get(base + "&cursor=" + first["next_cursor"]).json()
    assert {x["id"] for x in first["jobs"] + second["jobs"]} == ids
    anchored = c.get(base + "&cursor=" + first["next_cursor"] + "&include_anchor=true").json()
    assert anchored["jobs"][0]["id"] == first["next_cursor"] and len(anchored["jobs"]) == 3
    core.db.execute("UPDATE meeting_jobs SET state='SUPERSEDED' WHERE id=?", (first["next_cursor"],))
    after = c.get(base + "&cursor=" + first["next_cursor"])
    assert after.status_code == 200 and len(after.json()["jobs"]) == 2


def test_two_classifier_slots_are_bounded_and_admit_live_before_files(queued):
    c, core, service, wid, revision = queued
    release = threading.Event()
    entered = threading.Event()
    guard = threading.Lock()
    calls = []
    active = maximum = 0

    def classify(_wid, body, **kwargs):
        nonlocal active, maximum
        with guard:
            calls.append(body.utterance.utterance_id)
            active += 1
            maximum = max(maximum, active)
            if len(calls) == 2:
                entered.set()
        assert release.wait(3)
        with guard:
            active -= 1
        return SimpleNamespace(model_dump=lambda: label(1))

    service.classifier.classify = classify
    file = submit(c, wid, revision, index=0, origin="file")
    live = [submit(c, wid, revision, index=i) for i in range(1, 4)]
    try:
        service.tick()
        assert entered.wait(2)
        service.tick()
        assert set(calls) == {"utterance-1", "utterance-2"} and len(calls) == 2
        assert row(core, file)["state"] == "QUEUED"
        assert row(core, live[2])["state"] == "QUEUED"
    finally:
        release.set()
        for future in list(service.running.values()):
            future.result(timeout=3)
    step(service)
    assert maximum == 2
    assert sorted(calls) == [f"utterance-{i}" for i in range(4)]
    assert all(row(core, job)["state"] == "COMPLETED" for job in [file, *live])


def test_two_busy_classifiers_leave_both_answer_lanes_available(queued):
    c, core, service, wid, revision = queued
    release = threading.Event()
    all_entered = threading.Event()
    guard = threading.Lock()
    entered = []

    def block(stage, utterance_id):
        with guard:
            entered.append((stage, utterance_id))
            if len(entered) == 4:
                all_entered.set()
        assert release.wait(3)

    def classify(_wid, body, **kwargs):
        block("classify", body.utterance.utterance_id)
        return SimpleNamespace(model_dump=lambda: label(1))

    def retrieve(_wid, body, extraction):
        block("retrieve", body.utterance.utterance_id)
        saved = core.db.one("SELECT * FROM meeting_jobs WHERE utterance_id=?", (body.utterance.utterance_id,))
        return service._result(saved, "insufficient_evidence", "NO_EVIDENCE")

    service.classifier.classify = classify
    service.meeting.retrieve_classified = retrieve
    jobs = [submit(c, wid, revision, index=i) for i in range(4)]
    for job in jobs[2:]:
        core.db.execute("UPDATE meeting_jobs SET stage='retrieve',queue_class='PQ',score=4,classification=? WHERE id=?",
                        (dumps(label(4)), job["id"]))
    try:
        service.tick()
        assert all_entered.wait(2)
        assert {slot for slot in service.running} == {"filter", "filter-2", "priority", "shared"}
    finally:
        release.set()
        for future in list(service.running.values()):
            future.result(timeout=3)
    assert all(row(core, job)["state"] == "COMPLETED" for job in jobs)


def test_parallel_classification_cannot_publish_a_superseded_result(queued):
    c, core, service, wid, revision = queued
    release = threading.Event()
    both_entered = threading.Barrier(3)

    def classify(*args, **kwargs):
        both_entered.wait(timeout=3)
        assert release.wait(3)
        return SimpleNamespace(model_dump=lambda: label(1))

    service.classifier.classify = classify
    first, second = [submit(c, wid, revision, index=i) for i in (1, 2)]
    try:
        service.tick()
        both_entered.wait(timeout=2)
        changed = request()["utterance"]
        changed.update(utterance_id="utterance-1", revision=2, text="정정한 발화입니다")
        replacement = submit(c, wid, revision, index=1, utterance=changed, source_key="changed-source")
    finally:
        release.set()
        for future in list(service.running.values()):
            future.result(timeout=3)
    assert row(core, first)["state"] == "SUPERSEDED"
    assert row(core, first)["result"] is None
    assert row(core, second)["state"] == "COMPLETED"
    classify_as(service, 1)
    step(service)
    assert row(core, replacement)["state"] == "COMPLETED"


def test_fixed_delay_burst_comparison(queued, monkeypatch):
    """Synthetic scheduler measurement; no microphone, provider or live database."""
    import os
    from pathlib import Path

    c, core, service, wid, revision = queued
    measurements = []
    delay, count = 0.05, 8
    for slots in (1, 2):
        monkeypatch.setattr("meetingbot_rag.meeting_jobs.FILTER_SLOTS", tuple(f"filter-{i}" for i in range(slots)))
        active = maximum = 0
        guard = threading.Lock()

        def delayed(*args, **kwargs):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(delay)
            with guard:
                active -= 1
            return SimpleNamespace(model_dump=lambda: label(1))

        service.classifier.classify = delayed
        jobs = [submit(c, wid, revision, index=100 * slots + i) for i in range(count)]
        started = time.monotonic()
        for _ in range(count):
            step(service)
            if all(row(core, job)["state"] == "COMPLETED" for job in jobs):
                break
        elapsed_ms = round((time.monotonic() - started) * 1000, 2)
        assert maximum == slots
        assert all(row(core, job)["state"] == "COMPLETED" for job in jobs)
        measurements.append({"classifier_slots": slots, "jobs": count, "classifier_delay_ms": delay * 1000,
                             "elapsed_ms": elapsed_ms, "max_concurrent_classifiers": maximum})
    if target := os.environ.get("MEETING_BENCHMARK_REPORT"):
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(json.dumps({"kind": "synthetic_fixed_delay_classifier_burst",
                                           "real_microphone_or_llm": False, "measurements": measurements}, indent=2) + "\n")
