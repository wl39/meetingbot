#!/usr/bin/env python3
"""Synthetic SIGKILL/restart test of this installation's RAG LaunchAgent only."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))
from meetingbot_rag.settings import Settings

s = Settings()
key = s.auth_token_file.read_text().strip()
report = {"checks": []}
folder = Path.home() / "MeetingDocs" / ("recovery-test-" + str(os.getpid()))
folder.mkdir()
(folder / "logs.txt").write_text(
    "이것은 복구 검증용 합성 자료입니다. 로그 보관 기간은 90일입니다."
)
wid = None
c = httpx.Client(
    base_url=s.public_origin, headers={"Authorization": "Bearer " + key}, timeout=30
)


def wait_job(jid):
    for _ in range(150):
        job = c.get(f"/api/rag/workspaces/{wid}/index-jobs/{jid}").json()
        if job["state"] not in ("QUEUED", "RUNNING"):
            return job
        time.sleep(0.2)
    raise AssertionError("timeout")


try:
    existing = {
        w["id"]: w["active_revision_id"] for w in c.get("/api/rag/workspaces").json()
    }
    wid = c.post(
        "/api/rag/workspaces",
        json={
            "name": "복구 검증용 임시 공간",
            "root_id": "meeting-docs",
            "relative_path": folder.name,
        },
    ).json()["id"]
    first = c.post(f"/api/rag/workspaces/{wid}/index-jobs", json={}).json()
    first = wait_job(first["job_id"])
    assert first["state"] == "READY"
    old = first["revision_id"]
    for i in range(100):
        (folder / f"doc-{i}.txt").write_text(
            f"복구 테스트 자료 {i}.\n"
            + (
                "실제 회의 내용이 없는 합성 문서입니다. 자료 갱신 중 기존 버전을 유지합니다.\n"
                * 8
            )
        )
    job = c.post(f"/api/rag/workspaces/{wid}/index-jobs", json={}).json()
    for _ in range(100):
        state = c.get(f"/api/rag/workspaces/{wid}/index-jobs/{job['job_id']}").json()
        if state["state"] == "RUNNING":
            break
        time.sleep(0.01)
    assert state["state"] == "RUNNING"
    subprocess.run(
        ["launchctl", "kill", "SIGKILL", f"gui/{os.getuid()}/com.meetingbot.rag"],
        check=True,
    )
    for _ in range(90):
        try:
            status = c.get("/api/rag/diagnostics").json()
            if status["model"]["state"] == "READY":
                break
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("launchd restart or model load failed")
    recovered = c.get(f"/api/rag/workspaces/{wid}/index-jobs/{job['job_id']}").json()
    assert (
        recovered["state"] == "FAILED"
        and recovered["result"]["error_code"] == "SERVER_RESTARTED"
    ), recovered
    report["checks"].append(
        "SIGKILL running indexing job -> launchd restart -> durable SERVER_RESTARTED state"
    )
    ws = c.get(f"/api/rag/workspaces/{wid}").json()
    assert ws["active_revision_id"] == old
    search = c.post(
        f"/api/rag/workspaces/{wid}/search", json={"query": "로그 보관 기간"}
    ).json()
    assert search["revision_id"] == old and any(
        "90일" in e["text"] for e in search["evidence"]
    )
    report["checks"].append(
        "old READY revision, vector search and original evidence survive forced process termination"
    )
    for w in c.get("/api/rag/workspaces").json():
        if w["id"] in existing:
            assert w["active_revision_id"] == existing[w["id"]]
    report["checks"].append("other workspace active revisions unchanged after restart")
    report["recovery"] = {
        "state": recovered["state"],
        "error_code": recovered["result"]["error_code"],
    }
finally:
    if wid:
        c.delete("/api/rag/workspaces/" + wid).raise_for_status()
    c.close()
    shutil.rmtree(folder)
(ROOT / "docs/rag/recovery-test-results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print(json.dumps(report, ensure_ascii=False, indent=2))
