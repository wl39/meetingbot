"""Exercise both real HTTP/auth layers with fake speech, embeddings and LLM only."""

import json
import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers

from app.contracts.utterance import UtteranceEvent
from app.main import create_app
from app.modules.stt.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
KEY = "synthetic-e2e-administrator-credential-1234567890"


def eventually(read, accept, timeout=20):
    deadline = time.monotonic() + timeout
    value = None
    while time.monotonic() < deadline:
        value = read()
        if accept(value):
            return value
        time.sleep(0.05)
    raise AssertionError(f"Timed out waiting for synthetic processing: {value}")


@pytest.fixture
def integrated(tmp_path):
    python = ROOT / "rag/.venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not python.exists():
        pytest.skip("Install the RAG test environment to run the cross-service integration test")
    data = tmp_path / "stt"
    data.mkdir()
    token = data / "local-token"
    token.write_text(KEY)
    token.chmod(0o600)
    source = tmp_path / "source"
    source.mkdir()
    (source / "policy.md").write_text("# 운영 로그 정책\n\n운영서버 로그 기록의 보관 기간은 90일입니다.")
    roots = tmp_path / "roots.yaml"
    roots.write_text(json.dumps({"roots": [{"id": "docs", "label": "자료", "path": str(source)}]}))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = tmp_path / "rag.json"
    config.write_text(
        json.dumps(
            {
                "data_dir": str(tmp_path / "rag"),
                "source_roots_file": str(roots),
                "auth_token_file": str(token),
                "access_db": str(data / "access.sqlite3"),
                "port": port,
            }
        )
    )
    origin = f"http://127.0.0.1:{port}"
    log_path = tmp_path / "rag-process.log"
    with log_path.open("w+") as log:
        process = subprocess.Popen(
            [str(python), str(Path(__file__).parent / "fixtures/rag_meeting_server.py"), str(config)],
            stdout=log,
            stderr=log,
        )
        try:
            with httpx.Client(base_url=origin, headers={"Authorization": "Bearer " + KEY}, timeout=10) as rag:

                def ready():
                    assert process.poll() is None, log_path.read_text()
                    try:
                        return rag.get("/api/rag/auth/session").status_code
                    except httpx.ConnectError:
                        return 0

                eventually(ready, lambda status: status == 200)
                workspace = rag.post(
                    "/api/rag/workspaces", json={"name": "운영 정책", "root_id": "docs", "relative_path": ""}
                )
                assert workspace.status_code == 201, workspace.text
                wid = workspace.json()["id"]
                index = rag.post(f"/api/rag/workspaces/{wid}/index-jobs", json={})
                assert index.status_code == 202, index.text
                job = eventually(
                    lambda: rag.get(f"/api/rag/workspaces/{wid}/index-jobs/{index.json()['job_id']}").json(),
                    lambda value: value["state"] not in {"QUEUED", "RUNNING"},
                )
                assert job["state"] == "READY", job
                settings = rag.get("/api/rag/llm/settings").json()
                saved = rag.patch(
                    "/api/rag/llm/settings",
                    json={
                        "expected_version": settings["version"],
                        "enabled": True,
                        "api_key": "synthetic-provider-key",
                        "default_model": "fake",
                    },
                )
                assert saved.status_code == 200, saved.text
                approved = rag.patch(
                    f"/api/rag/workspaces/{wid}",
                    json={"external_llm_approved": True, "provider_id": saved.json()["provider_id"]},
                )
                assert approved.status_code == 200, approved.text
                app = create_app(
                    Settings(_env_file=None, engine="fake", data_dir=data, rag_base_url=origin), FakeWorkers
                )
                with TestClient(app) as client:
                    visitor = app.state.access.issue_key("Synthetic owner", "visitor")
                    client.headers["Authorization"] = "Bearer " + visitor["key"]
                    yield client, rag, wid, visitor
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.parametrize("mode", ["microphone", "file"])
def test_real_bridge_keeps_low_scores_prioritizes_claims_and_reclassifies_corrections(integrated, mode):
    client, rag, wid, visitor = integrated
    repo = client.app.state.service.repo
    if mode == "microphone":
        session = client.post("/api/stt/sessions", json={}).json()
    else:
        session = repo.create("file", {}, {})
        client.app.state.access.owner(session["id"], visitor["id"])
    sid = session["id"]
    texts = ["어", "안녕하세요", "운영서버 로그 기록은 45일 동안 보관합니다."]
    session["utterances"] = [
        UtteranceEvent(
            session_id=sid, input_mode=mode, start_ms=i * 1000, end_ms=(i + 1) * 1000, text=text
        ).model_dump()
        for i, text in enumerate(texts)
    ]
    repo.save(session)
    outgoing = []
    admissions = []
    original = client.app.state.rag_bridge.opener.open

    def record(request, **kwargs):
        outgoing.append(
            (
                request.full_url,
                request.get_header("X-meeting-subscription"),
                request.get_header("Authorization") == "Bearer " + KEY,
            )
        )
        if request.full_url.endswith("/meeting/jobs") and request.data:
            admissions.append(json.loads(request.data))
        return original(request, **kwargs)

    client.app.state.rag_bridge.opener.open = record
    path = f"/api/stt/meeting/sessions/{sid}"
    subscribed = client.put(path + "/subscription", json={"workspace_id": wid, "enabled": True})
    assert subscribed.status_code == 200, subscribed.text

    # Browser polling has no role in submitting speech; only observe the durable server results.
    def read_jobs():
        response = client.get(path + f"/jobs?workspace_id={wid}")
        assert response.status_code == 200, response.text
        return response.json()["jobs"]

    jobs = eventually(
        read_jobs, lambda values: len(values) == 3 and all(j["state"] == "COMPLETED" for j in values)
    )
    by_text = {job["text"]: job for job in jobs}
    assert [by_text[text]["score"] for text in texts] == [1, 2, 4]
    assert by_text[texts[-1]]["queue_class"] == "PQ"
    assert all(job["origin"] == ("live" if mode == "microphone" else "file") for job in jobs)
    internal = [call for call in outgoing if call[0].endswith("/meeting/jobs")]
    assert internal and all(header == "1" and service_identity for _, header, service_identity in internal)
    assert all(payload["source_generation"] == session["snapshot_revision"] for payload in admissions)
    assert all(job.get("owner", visitor["id"]) == visitor["id"] for job in jobs)
    outsider = client.app.state.access.issue_key("Other visitor", "visitor")
    denied = rag.get(
        f"/api/rag/workspaces/{wid}/meeting/jobs?session_id={sid}",
        headers={"Authorization": "Bearer " + outsider["key"]},
    )
    assert denied.status_code == 404
    # Visitors cannot manufacture the privileged worker channel to submit arbitrary identities.
    denied = rag.post(
        f"/api/rag/workspaces/{wid}/meeting/sessions/{sid}/sync",
        headers={"Authorization": "Bearer " + visitor["key"], "X-Meeting-Subscription": "1"},
        json={"utterance_ids": [], "generation": 99},
    )
    assert denied.status_code == 403
    # The STT bridge preserves bounded pages and the server's opaque cursor unchanged.
    seen, cursor = [], None
    for _ in range(3):
        params = {"workspace_id": wid, "limit": 1}
        if cursor:
            params["cursor"] = cursor
        page = client.get(path + "/jobs", params=params)
        assert page.status_code == 200, page.text
        assert len(page.json()["jobs"]) == 1
        seen.extend(job["id"] for job in page.json()["jobs"])
        cursor = page.json().get("next_cursor")
    assert len(set(seen)) == 3 and cursor is None
    uid = session["utterances"][-1]["utterance_id"]
    corrected = client.patch(
        f"/api/stt/sessions/{sid}/utterances/{uid}",
        json={"base_revision": 1, "text": "개인 프로젝트 이야기예요"},
    )
    assert corrected.status_code == 200, corrected.text
    jobs = eventually(
        read_jobs,
        lambda values: (
            len(values) == 3
            and all(j["state"] == "COMPLETED" for j in values)
            and any(j["utterance_id"] == uid and j["score"] == 2 for j in values)
        ),
    )
    assert next(j for j in jobs if j["utterance_id"] == uid)["utterance_revision"] == 2
    # The public installation key plus the marker alone cannot impersonate STT.
    forged = rag.post(
        f"/api/rag/workspaces/{wid}/meeting/jobs",
        json=admissions[0],
        headers={"Authorization": "Bearer " + KEY, "X-Meeting-Subscription": "1"},
    )
    assert forged.status_code == 403, forged.text
    stale = rag.post(
        f"/api/rag/workspaces/{wid}/meeting/jobs",
        json=admissions[0],
        headers={
            "Authorization": "Bearer " + KEY,
            "X-Meeting-Subscription": "1",
            "X-Meeting-Bridge-Secret": client.app.state.access.service_secret("meeting-subscription"),
        },
    )
    assert stale.status_code == 409, stale.text
    assert client.delete(f"/api/stt/sessions/{sid}").status_code == 204
    eventually(lambda: repo.meeting_subscription(sid), lambda subscription: subscription is None)
    assert rag.get(f"/api/rag/workspaces/{wid}/meeting/jobs?session_id={sid}").status_code == 404
    owned = rag.get(
        f"/api/rag/workspaces/{wid}/meeting/jobs?session_id={sid}",
        headers={"Authorization": "Bearer " + visitor["key"]},
    )
    assert owned.status_code == 200 and owned.json()["jobs"] == []
