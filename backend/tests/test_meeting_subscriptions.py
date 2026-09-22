import json
import time
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.responses import JSONResponse
from test_meeting_bridge import WID, transcript
from test_meeting_bridge import meeting_client as meeting_client

from app.contracts.utterance import UtteranceEvent
from app.modules.meeting.subscriptions import SubscriptionDelivery, source_hash, source_payloads
from app.modules.stt.repository import Repository


def setup_repository(tmp_path, count=3, mode="microphone"):
    repo = Repository(tmp_path / "stt.sqlite3")
    session = repo.create(mode, {}, {})
    session["utterances"] = [UtteranceEvent(
        session_id=session["id"], input_mode=mode, start_ms=i * 1000, end_ms=(i + 1) * 1000,
        text=["어", "안녕하세요", "운영 로그는 45일 보관합니다"][i % 3],
    ).model_dump() for i in range(count)]
    repo.save(session)
    subscription = {"session_id": session["id"], "workspace_id": WID, "revision_id": None,
                    "enabled": True, "subject": "verified-subject", "generation": 1,
                    "enabled_at": time.time(), "origin": "file" if mode == "file" else "live"}
    repo.save_meeting_subscription(subscription)
    return repo, session, subscription


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.fail = False

    def request(self, path, body=None, *, subscription=False):
        assert subscription
        self.calls.append((path, body))
        if self.fail:
            return JSONResponse({"detail": "RAG_UNAVAILABLE"}, 503)
        return {"accepted": True}

    @property
    def jobs(self):
        return [body for path, body in self.calls if path.endswith("/meeting/jobs")]


@pytest.mark.asyncio
async def test_all_speech_survives_restart_and_acknowledged_work_is_not_resent(tmp_path):
    repo, session, subscription = setup_repository(tmp_path)
    bridge = FakeBridge()
    # No browser or socket participates in delivery, including after service restart.
    repo.db.close()
    repo = Repository(tmp_path / "stt.sqlite3")
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    assert [job["utterance"]["text"] for job in bridge.jobs] == ["어", "안녕하세요", "운영 로그는 45일 보관합니다"]
    assert all(job["received_at"] >= subscription["enabled_at"] for job in bridge.jobs)
    assert len(bridge.jobs[0]["following_context"]) == 2
    assert bridge.jobs[1]["context"][0]["utterance_id"] == session["utterances"][0]["utterance_id"]
    repo.db.close()
    repo = Repository(tmp_path / "stt.sqlite3")
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert len(bridge.jobs) == 3
    repo.db.close()


@pytest.mark.asyncio
async def test_rag_failure_is_retried_without_losing_original_timestamp(tmp_path):
    repo, _, subscription = setup_repository(tmp_path, count=1)
    bridge = FakeBridge()
    bridge.fail = True
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    assert repo.meeting_subscription(subscription["session_id"])["last_error"] == "RAG_UNAVAILABLE"
    # Allow sync and fail admission to exercise a receipt before upstream acceptance.
    bridge.fail = False
    original = bridge.request

    def fail_job(path, body=None, **kwargs):
        result = original(path, body, **kwargs)
        return JSONResponse({"detail": "LLM_BUSY"}, 429) if path.endswith("/meeting/jobs") else result

    bridge.request = fail_job
    subscription = repo.meeting_subscription(subscription["session_id"])
    subscription["next_attempt_at"] = 0
    repo.save_meeting_subscription(subscription)
    await worker.poll()
    first = bridge.jobs[0]
    bridge.request = original
    subscription = repo.meeting_subscription(subscription["session_id"])
    subscription["next_attempt_at"] = 0
    repo.save_meeting_subscription(subscription)
    await worker.poll()
    assert bridge.jobs[1]["source_key"] == first["source_key"]
    assert bridge.jobs[1]["received_at"] == first["received_at"]
    repo.db.close()


@pytest.mark.asyncio
async def test_correction_and_following_context_get_new_source_keys(tmp_path):
    repo, session, subscription = setup_repository(tmp_path)
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    before = {job["utterance"]["utterance_id"]: job["source_key"] for job in bridge.jobs}
    session = repo.get(session["id"])
    session["utterances"][-1].update(text="개인 프로젝트에 관한 이야기예요", revision=2, status="corrected")
    repo.save(session)
    await worker.poll()
    after = {job["utterance"]["utterance_id"]: job["source_key"] for job in bridge.jobs[3:]}
    assert len(after) == 3 and all(before[uid] != key for uid, key in after.items())
    assert bridge.jobs[-1]["utterance"]["status"] == "stable"
    # Retractions are reconciled upstream even when there are no replacement utterances.
    session["utterances"] = []
    repo.save(session)
    await worker.poll()
    assert bridge.calls[-1][1]["utterance_ids"] == []
    repo.db.close()


@pytest.mark.asyncio
async def test_file_admission_is_bounded_and_eventually_delivers_everything(tmp_path):
    repo, _, _ = setup_repository(tmp_path, count=13, mode="file")
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    assert len(bridge.jobs) == 4
    for _ in range(3):
        await worker.poll()
    assert len(bridge.jobs) == 13
    assert all(job["origin"] == "file" for job in bridge.jobs)
    repo.db.close()


@pytest.mark.asyncio
async def test_deletion_tombstone_retries_until_upstream_deleted(tmp_path):
    repo, session, _ = setup_repository(tmp_path)
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    repo.delete(session["id"])
    assert repo.meeting_subscription(session["id"])["deleted"]
    bridge.fail = True
    await worker.poll()
    assert repo.meeting_subscription(session["id"])["cleanup_pending"]
    bridge.fail = False
    subscription = repo.meeting_subscription(session["id"])
    subscription["next_attempt_at"] = 0
    repo.save_meeting_subscription(subscription)
    await worker.poll()
    assert bridge.calls[-1][0].endswith("/cancel")
    assert bridge.calls[-1][1] == {"delete": True}
    assert repo.meeting_subscription(session["id"]) is None
    repo.db.close()


@pytest.mark.asyncio
async def test_completed_idle_session_never_sends_periodic_network_heartbeats(tmp_path, monkeypatch):
    repo, session, _ = setup_repository(tmp_path)
    repo.state(session["id"], "COMPLETED")
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    assert len(bridge.jobs) == 3
    bridge.calls.clear()
    later = time.time() + 3600
    monkeypatch.setattr("app.modules.meeting.subscriptions.time.time", lambda: later)
    for _ in range(6):
        await worker.poll()
    assert bridge.calls == []
    repo.db.close()


def test_subscription_never_persists_auth_headers_and_put_is_idempotent(meeting_client, monkeypatch):
    client = meeting_client
    body = transcript(client)
    sid = body["session_id"]
    calls = []

    def upstream(path, body=None, caller_headers=None, **kwargs):
        calls.append((path, caller_headers, kwargs))
        return {"enabled": True}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    path = f"/api/stt/meeting/sessions/{sid}/subscription"
    assert client.get(path).json() == {"enabled": False, "workspace_id": None, "revision_id": None}
    assert client.put(path, json={"enabled": True, "workspace_id": WID}).status_code == 200
    assert client.put(path, json={"enabled": True, "workspace_id": WID}).status_code == 200
    subscription = client.app.state.service.repo.meeting_subscription(sid)
    assert subscription["generation"] == 1
    assert subscription["subject"] == "superadmin"
    assert client.app.state.token not in json.dumps(subscription)
    assert calls[0][1]["Authorization"] == "Bearer " + client.app.state.token
    assert client.put(path, json={"enabled": False, "workspace_id": WID}).json()["enabled"] is False


def test_subscription_routes_require_session_ownership(meeting_client, monkeypatch):
    client = meeting_client
    sid = transcript(client)["session_id"]
    visitor = client.app.state.access.issue_key("Visitor", "visitor")
    paths = [("get", f"/api/stt/meeting/sessions/{sid}/subscription", None),
             ("put", f"/api/stt/meeting/sessions/{sid}/subscription", {"enabled": True, "workspace_id": WID}),
             ("get", f"/api/stt/meeting/sessions/{sid}/jobs?workspace_id={WID}", None),
             ("post", f"/api/stt/meeting/sessions/{sid}/jobs/job_123/retry", {"workspace_id": WID})]

    def forbidden(*args, **kwargs):
        pytest.fail("Another visitor's session may not reach RAG")

    monkeypatch.setattr(client.app.state.rag_bridge, "request", forbidden)
    client.headers["Authorization"] = "Bearer " + visitor["key"]
    for method, path, body in paths:
        response = client.request(method.upper(), path, json=body)
        assert response.status_code == 404, response.text


def test_jobs_hides_result_if_source_was_changed_during_upstream_read(meeting_client, monkeypatch):
    client = meeting_client
    body = transcript(client)
    sid = body["session_id"]
    repo = client.app.state.service.repo
    subscription = {"session_id": sid, "workspace_id": WID, "revision_id": None, "enabled": False}
    repo.save_meeting_subscription(subscription)
    payload = list(source_payloads(repo.get(sid), subscription))[-1]

    def upstream(*args, **kwargs):
        session = repo.get(sid)
        session["utterances"][-1].update(text="로그는 90일 보관합니다", revision=2)
        repo.save(session)
        return {"jobs": [{"id": "old", "source_key": payload["source_key"]}]}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    response = client.get(f"/api/stt/meeting/sessions/{sid}/jobs?workspace_id={WID}")
    assert response.status_code == 200
    assert response.json()["jobs"] == []


def test_source_generation_does_not_change_keys_and_context_is_not_truncated(tmp_path):
    repo, session, subscription = setup_repository(tmp_path)
    complete = "운영 서비스에 관한 설명입니다. " * 90 + "하지만 개인 프로젝트의 Docker를 말한 것은 아닙니다."
    assert 1500 < len(complete) <= 10000
    session["utterances"][1]["text"] = complete
    repo.save(session)
    first = list(source_payloads(session, subscription))
    assert first[0]["following_context"][0]["text"] == complete
    assert first[-1]["context"][-1]["text"] == complete
    assert first[0]["source_generation"] == session["snapshot_revision"]
    # Saving unrelated speaker display metadata changes the snapshot, not the semantic source.
    session["speakers"]["speaker-display"] = "화자 표시명"
    repo.save(session)
    later = list(source_payloads(session, subscription))
    assert later[0]["source_generation"] > first[0]["source_generation"]
    assert [p["source_key"] for p in later] == [p["source_key"] for p in first]
    repo.db.close()


@pytest.mark.asyncio
async def test_metadata_revisions_and_finalization_preserve_inflight_analysis(tmp_path):
    repo, session, _ = setup_repository(tmp_path)
    bridge = FakeBridge()
    await SubscriptionDelivery(repo, bridge, None).poll()
    original = [job["source_key"] for job in bridge.jobs]
    session = repo.get(session["id"])
    for utterance in session["utterances"]:
        utterance.update(revision=utterance["revision"] + 5, status="final")
    repo.save(session)
    # Restart is intentional: the semantic identity must survive process boundaries.
    await SubscriptionDelivery(repo, bridge, None).poll()
    subscription = repo.meeting_subscription(session["id"])
    payloads = list(source_payloads(session, subscription))
    assert [p["source_key"] for p in payloads] == original
    assert all(p["utterance"]["revision"] == 6 for p in payloads)
    assert len(bridge.jobs) == 3
    repo.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_upgrade_reuses_legacy_receipts_without_replaying_completed_sessions(tmp_path, acknowledged):
    repo, session, subscription = setup_repository(tmp_path)
    repo.state(session["id"], "COMPLETED")
    session = repo.get(session["id"])
    legacy = []
    for payload in source_payloads(session, subscription):
        source = {k: v for k, v in payload.items() if k not in {"source_key", "source_generation"}}
        key = source_hash({**source, "subscription_generation": subscription["generation"]})
        legacy.append(key)
        repo.meeting_delivery(session["id"], key, subscription["enabled_at"])
        if acknowledged:
            repo.acknowledge_meeting_delivery(session["id"], key)
    bridge = FakeBridge()
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert [p["source_key"] for p in source_payloads(session, repo.meeting_subscription(session["id"]))] == legacy
    assert [p["source_key"] for p in bridge.jobs] == ([] if acknowledged else legacy)
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert len(bridge.jobs) == (0 if acknowledged else 3)
    repo.db.close()


@pytest.mark.asyncio
async def test_content_reversion_and_reinsertion_get_new_durable_incarnations(tmp_path):
    repo, session, _ = setup_repository(tmp_path, count=1)
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    session = repo.get(session["id"])
    utterance = session["utterances"][0]
    original = utterance["text"]
    for text in ("수정한 문장입니다", original):
        utterance.update(text=text, revision=utterance["revision"] + 1)
        repo.save(session)
        await worker.poll()
    assert len(bridge.jobs) == 3
    assert len({p["source_key"] for p in bridge.jobs}) == 3
    session["utterances"] = []
    repo.save(session)
    await worker.poll()
    session["utterances"] = [utterance]
    repo.save(session)
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert len(bridge.jobs) == 4
    assert len({p["source_key"] for p in bridge.jobs}) == 4
    repo.db.close()


@pytest.mark.asyncio
async def test_changed_context_keeps_new_key_across_failed_sync_and_restart(tmp_path):
    repo, session, _ = setup_repository(tmp_path)
    bridge = FakeBridge()
    worker = SubscriptionDelivery(repo, bridge, None)
    await worker.poll()
    session = repo.get(session["id"])
    session["utterances"][-1].update(text="이전 설명을 정정합니다", revision=2)
    repo.save(session)
    bridge.fail = True
    await worker.poll()
    subscription = repo.meeting_subscription(session["id"])
    pending = [p["source_key"] for p in source_payloads(session, subscription)]
    assert set(pending).isdisjoint(p["source_key"] for p in bridge.jobs)
    subscription["next_attempt_at"] = 0
    repo.save_meeting_subscription(subscription)
    bridge.fail = False
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert [p["source_key"] for p in bridge.jobs[3:]] == pending
    repo.db.close()


@pytest.mark.asyncio
async def test_correction_during_admission_is_reconciled_once_after_restart(tmp_path):
    repo, session, _ = setup_repository(tmp_path)
    bridge = FakeBridge()
    original = bridge.request

    def correction_during_request(path, body=None, **kwargs):
        response = original(path, body, **kwargs)
        if path.endswith("/meeting/jobs") and len(bridge.jobs) == 1:
            latest = repo.get(session["id"])
            latest["utterances"][-1].update(text="응답을 기다리던 중 수정한 문장입니다", revision=2)
            repo.save(latest)
        return response

    bridge.request = correction_during_request
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert len(bridge.jobs) == 1
    stale = bridge.jobs[0]["source_key"]
    current = list(source_payloads(repo.get(session["id"]), repo.meeting_subscription(session["id"])))
    assert stale not in {p["source_key"] for p in current}
    bridge.request = original
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert [p["source_key"] for p in bridge.jobs[1:]] == [p["source_key"] for p in current]
    await SubscriptionDelivery(repo, bridge, None).poll()
    assert len(bridge.jobs) == 4
    repo.db.close()


def test_jobs_preserves_pagination_and_encodes_the_opaque_cursor(meeting_client, monkeypatch):
    client = meeting_client
    sid = transcript(client)["session_id"]
    calls = []
    next_cursor = "123.4:next/job+token=="

    def upstream(path, **kwargs):
        calls.append(path)
        return {"jobs": [], "next_cursor": next_cursor, "scheduler": {"mode": "NORMAL"}, "policy": {}}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    path = f"/api/stt/meeting/sessions/{sid}/jobs"
    response = client.get(path, params={"workspace_id": WID, "limit": 2, "cursor": next_cursor})
    assert response.status_code == 200, response.text
    assert parse_qs(urlsplit(calls[-1]).query) == {"session_id": [sid], "limit": ["2"], "cursor": [next_cursor]}
    assert response.json()["next_cursor"] == next_cursor
    assert response.json()["scheduler"] == {"mode": "NORMAL"}
    assert client.get(path, params={"workspace_id": WID, "cursor": next_cursor,
                                   "include_anchor": True}).status_code == 200
    assert parse_qs(urlsplit(calls[-1]).query)["include_anchor"] == ["true"]
    assert client.get(path, params={"workspace_id": WID}).status_code == 200
    assert parse_qs(urlsplit(calls[-1]).query)["limit"] == ["15"]
    assert client.get(path, params={"workspace_id": WID, "limit": 0}).status_code == 422


def test_rapid_workspace_switch_does_not_cancel_the_newly_selected_grant(meeting_client, monkeypatch):
    client = meeting_client
    sid = transcript(client)["session_id"]
    delivery = client.app.state.meeting_delivery
    poll = delivery.poll

    async def paused():
        pass

    monkeypatch.setattr(delivery, "poll", paused)
    calls = []

    def upstream(path, body=None, **kwargs):
        calls.append((path, body))
        return {"enabled": True}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    path = f"/api/stt/meeting/sessions/{sid}/subscription"
    other = "b" * 32
    for wid in (WID, other, WID):
        assert client.put(path, json={"workspace_id": wid, "enabled": True}).status_code == 200
    subscription = client.app.state.service.repo.meeting_subscription(sid)
    assert subscription["pending_cleanup"] == [other]
    client.portal.call(poll)
    assert not any(endpoint == f"/workspaces/{WID}/meeting/sessions/{sid}/cancel" for endpoint, _ in calls)
    assert any(endpoint == f"/workspaces/{other}/meeting/sessions/{sid}/cancel" for endpoint, _ in calls)
    assert len([body for endpoint, body in calls if endpoint == f"/workspaces/{WID}/meeting/jobs"]) == 5


@pytest.mark.parametrize("cancel_before_reenable", [False, True])
def test_disable_reenable_creates_new_receipts_without_cancelling_reopened_grant(
    meeting_client, monkeypatch, cancel_before_reenable,
):
    client = meeting_client
    sid = transcript(client)["session_id"]
    delivery = client.app.state.meeting_delivery
    poll = delivery.poll

    async def paused():
        pass

    monkeypatch.setattr(delivery, "poll", paused)
    calls = []

    def upstream(path, body=None, **kwargs):
        calls.append((path, body))
        return {"enabled": True}

    monkeypatch.setattr(client.app.state.rag_bridge, "request", upstream)
    path = f"/api/stt/meeting/sessions/{sid}/subscription"
    assert client.put(path, json={"workspace_id": WID, "enabled": True}).status_code == 200
    client.portal.call(poll)
    first = {body["source_key"] for endpoint, body in calls if endpoint.endswith("/meeting/jobs")}
    assert len(first) == 5
    assert client.put(path, json={"workspace_id": WID, "enabled": False}).status_code == 200
    if cancel_before_reenable:
        client.portal.call(poll)
    calls.clear()
    assert client.put(path, json={"workspace_id": WID, "enabled": True}).status_code == 200
    client.portal.call(poll)
    second = {body["source_key"] for endpoint, body in calls if endpoint.endswith("/meeting/jobs")}
    assert len(second) == 5 and first.isdisjoint(second)
    assert not any(endpoint.endswith("/cancel") for endpoint, _ in calls)
