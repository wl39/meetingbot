"""A user's installation key cannot impersonate the durable STT worker."""

import pytest
from conftest import KEY
from meetingbot_access import AccessStore
from test_meeting import request
from test_meeting_jobs import queued as queued


@pytest.fixture
def victim(queued):
    client, core, service, wid, revision = queued
    store = client.app.state.access
    owner = store.issue_key("Private meeting owner", "visitor")
    sid = "private-visitor-session"
    store.owner(sid, owner["id"])
    headers = {"Authorization": "Bearer " + owner["key"]}
    base = f"/api/rag/workspaces/{wid}/meeting"
    subscribed = client.post(
        base + f"/sessions/{sid}/subscription",
        headers=headers,
        json={"enabled": True, "revision_id": revision},
    )
    assert subscribed.status_code == 200, subscribed.text
    body = request(session_id=sid, revision_id=revision, source_key="known-source-key", origin="live")
    admitted = client.post(base + "/jobs", headers=headers, json=body)
    assert admitted.status_code == 202, admitted.text
    return client, core, base, sid, body, admitted.json(), owner


@pytest.mark.parametrize("action", ["jobs", "sync", "cancel"])
def test_installation_key_and_forged_worker_header_cannot_read_or_mutate_other_records(victim, action):
    client, core, base, sid, body, job, _ = victim
    url = base + ("/jobs" if action == "jobs" else f"/sessions/{sid}/{action}")
    payload = (
        body
        if action == "jobs"
        else {"utterance_ids": [], "generation": 999}
        if action == "sync"
        else {"delete": True}
    )
    # Includes the idempotency path which used to return the existing private job.
    before = dict(core.db.one("SELECT * FROM meeting_jobs WHERE id=?", (job["id"],)))
    grant = dict(core.db.one("SELECT * FROM meeting_subscriptions WHERE session_id=?", (sid,)))
    assert client.post(url, json=payload).status_code == 404
    for forged in (None, "wrong-secret", KEY):
        headers = {"X-Meeting-Subscription": "1"}
        if forged is not None:
            headers["X-Meeting-Bridge-Secret"] = forged
        response = client.post(url, headers=headers, json=payload)
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "ROLE_DENIED"
    assert dict(core.db.one("SELECT * FROM meeting_jobs WHERE id=?", (job["id"],))) == before
    assert dict(core.db.one("SELECT * FROM meeting_subscriptions WHERE session_id=?", (sid,))) == grant


@pytest.mark.parametrize("role", ["visitor", "admin", "superadmin"])
def test_issued_user_keys_cannot_use_worker_channel_even_with_the_secret(victim, role):
    client, _, base, sid, _, _, _ = victim
    store = client.app.state.access
    user = store.issue_key("Another user", role)
    response = client.post(
        base + f"/sessions/{sid}/sync",
        headers={
            "Authorization": "Bearer " + user["key"],
            "X-Meeting-Subscription": "1",
            "X-Meeting-Bridge-Secret": store.service_secret("meeting-subscription"),
        },
        json={"utterance_ids": [], "generation": 999},
    )
    assert response.status_code == 403


def test_authentication_precedes_deleted_workspace_cleanup_shortcut(victim):
    client, _, _, sid, _, _, _ = victim
    response = client.post(
        f"/api/rag/workspaces/{'f' * 32}/meeting/sessions/{sid}/cancel",
        headers={"X-Meeting-Subscription": "1"},
        json={"delete": True},
    )
    assert response.status_code == 403


def test_real_worker_authentication_survives_reopening_the_shared_store(victim):
    client, core, base, sid, body, job, owner = victim
    store = client.app.state.access
    original = store.service_secret("meeting-subscription")
    reopened = AccessStore(store.token_file, store.path)
    client.app.state.access = reopened
    headers = {"X-Meeting-Subscription": "1", "X-Meeting-Bridge-Secret": original}
    # The secret alone never changes a normal user request into a worker request.
    assert (
        client.post(base + "/jobs", headers={"X-Meeting-Bridge-Secret": original}, json=body).status_code
        == 404
    )
    admitted = client.post(base + "/jobs", headers=headers, json=body)
    assert admitted.status_code == 202 and admitted.json()["id"] == job["id"]
    assert core.db.one("SELECT owner FROM meeting_jobs WHERE id=?", (job["id"],))["owner"] == owner["id"]
    synced = client.post(
        base + f"/sessions/{sid}/sync",
        headers=headers,
        json={"utterance_ids": [body["utterance"]["utterance_id"]], "generation": 1},
    )
    assert synced.status_code == 200, synced.text
    cancelled = client.post(base + f"/sessions/{sid}/cancel", headers=headers, json={})
    assert cancelled.status_code == 200, cancelled.text
