#!/usr/bin/env python3
"""Real deployed HTTPS integration smoke using synthetic samples only. Never logs credentials."""

import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))
from meetingbot_rag.settings import Settings

s = Settings()
origin = s.public_origin or "http://127.0.0.1:8766"
report = {
    "origin": origin,
    "network_scope": "server host through Tailscale Serve HTTPS (not a second remote device)",
    "checks": [],
    "jobs": [],
    "evaluation": [],
}
key = s.auth_token_file.read_text().strip()


def check(condition, name):
    assert condition, name
    report["checks"].append(name)


with httpx.Client(base_url=origin, timeout=90) as c:
    check(c.get("/rag").status_code == 200, "production web served over TLS")
    check(
        c.get("/api/rag/source-roots").status_code == 401,
        "unauthenticated roots denied",
    )
    r = c.post("/api/rag/auth/login", json={"key": key}, headers={"Origin": origin})
    check(r.status_code == 200, "HTTPS administrator login")
    check(
        "Secure" in r.headers.get("set-cookie", "")
        and "HttpOnly" in r.headers["set-cookie"],
        "Secure HttpOnly session",
    )
    csrf = r.json()["csrf"]
    c.headers.update({"Origin": origin, "X-CSRF-Token": csrf})
    check(
        c.post(
            "/api/rag/workspaces",
            json={"name": "CSRF should fail"},
            headers={"X-CSRF-Token": ""},
        ).status_code
        == 403,
        "CSRF enforced over HTTPS",
    )
    check(
        c.get(
            "/api/rag/source-roots", headers={"Origin": "https://evil.example"}
        ).status_code
        == 403,
        "foreign Origin denied over HTTPS",
    )
    for _ in range(60):
        health = c.get("/api/rag/diagnostics").json()
        if health["model"]["state"] == "READY":
            break
        if health["model"]["state"] == "NOT_READY":
            raise AssertionError(health)
        time.sleep(1)
    check(health["model"]["state"] == "READY", "real multilingual E5 model ready")
    report["model"] = health["model"]
    spaces = c.get("/api/rag/workspaces").json()
    ids = {}
    for folder, name in [
        ("sample-project-a", "샘플 프로젝트 A"),
        ("sample-project-b", "샘플 프로젝트 B"),
    ]:
        ws = next(
            (
                w
                for w in spaces
                if w["name"] == name and w["source"]["relative_path"] == folder
            ),
            None,
        )
        if not ws:
            response = c.post(
                "/api/rag/workspaces",
                json={
                    "name": name,
                    "description": "개인정보 없는 합성 자료 · 로그 보관 정책 검증",
                    "root_id": "meeting-docs",
                    "relative_path": folder,
                },
            )
            check(response.status_code == 201, "create " + folder)
            ws = response.json()
        ids[folder.removeprefix("sample-")] = ws["id"]
        result = c.post(f"/api/rag/workspaces/{ws['id']}/index-jobs", json={})
        check(result.status_code == 202, "persistent index job " + folder)
        jid = result.json()["job_id"]
        started = time.monotonic()
        for _ in range(120):
            job = c.get(f"/api/rag/workspaces/{ws['id']}/index-jobs/{jid}").json()
            if job["state"] not in ("QUEUED", "RUNNING"):
                break
            time.sleep(0.5)
        check(
            job["state"] == "READY",
            "real index READY "
            + folder
            + " "
            + str(job.get("result", {}).get("error_code")),
        )
        report["jobs"].append(
            {
                "workspace": folder,
                "revision_id": job["revision_id"],
                "result": job["result"],
                "wall_seconds": round(time.monotonic() - started, 3),
            }
        )
    for test in json.loads((ROOT / "samples/rag/evaluation.json").read_text()):
        wid = ids[test["workspace"]]
        response = c.post(
            f"/api/rag/workspaces/{wid}/search", json={"query": test["query"]}
        )
        check(response.status_code == 200, "search " + test["query"])
        result = response.json()
        hits = [
            e
            for e in result["evidence"]
            if e["relative_path"] == test["path"] and test["contains"] in e["text"]
        ]
        check(
            bool(hits),
            "expected Korean evidence " + test["workspace"] + " " + test["query"],
        )
        check(
            all(e["workspace_id"] == wid for e in result["evidence"]),
            "workspace scoped evidence",
        )
        evidence = hits[0]
        snapshot = c.get(
            f"/api/rag/workspaces/{wid}/evidence/{evidence['evidence_id']}",
            params={"revision_id": result["revision_id"]},
        )
        check(
            snapshot.status_code == 200
            and snapshot.json()["source"] == "revision_snapshot",
            "versioned source snapshot",
        )
        report["evaluation"].append(
            {
                "query": test["query"],
                "workspace": test["workspace"],
                "evidence": evidence,
                "timings_ms": result["timings_ms"],
            }
        )
    a, b = ids["project-a"], ids["project-b"]
    ev = report["evaluation"][0]["evidence"]
    check(
        c.get(
            f"/api/rag/workspaces/{b}/evidence/{ev['evidence_id']}",
            params={"revision_id": ev["revision_id"]},
        ).status_code
        in (404, 409),
        "cross workspace source lookup denied",
    )
    answer = c.post(
        f"/api/rag/workspaces/{a}/questions",
        json={"query": "로그 보관 기간은 얼마인가요?"},
    ).json()
    for _ in range(300):
        if answer["status"] not in {"queued", "processing"}:
            break
        time.sleep(0.2)
        answer = c.get(f"/api/rag/history/{answer['request_id']}").json()["result"]
    check(
        answer["status"] == "llm_unavailable"
        and answer["reason"] == "EXTERNAL_LLM_NOT_APPROVED",
        "unapproved external LLM disabled, local evidence retained",
    )
    report["llm"] = c.post("/api/rag/diagnostics/llm-check", json={}).json()
    before = c.get("/api/rag/diagnostics").json()["model"]["encoded_passages"]
    job = c.post(f"/api/rag/workspaces/{a}/index-jobs", json={}).json()
    for _ in range(100):
        job = c.get(f"/api/rag/workspaces/{a}/index-jobs/{job['job_id']}").json()
        if job["state"] not in ("QUEUED", "RUNNING"):
            break
        time.sleep(0.2)
    after = c.get("/api/rag/diagnostics").json()["model"]["encoded_passages"]
    check(
        job["state"] == "READY"
        and before == after
        and job["result"]["reused_documents"] == 4,
        "unchanged real documents reuse embeddings",
    )
    report["incremental"] = {
        "before_encoded": before,
        "after_encoded": after,
        "reused_documents": job["result"]["reused_documents"],
    }
    with httpx.Client(
        base_url="http://127.0.0.1:8766", headers={"Authorization": "Bearer " + key}
    ) as local:
        local_spaces = local.get("/api/rag/workspaces").json()
        check(
            {w["id"] for w in local_spaces}
            == {w["id"] for w in c.get("/api/rag/workspaces").json()},
            "local and HTTPS see identical persisted workspace IDs",
        )
    report["workspace_ids"] = ids
(ROOT / "docs/rag/real-integration-results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
print(
    json.dumps(
        {
            "checks_passed": len(report["checks"]),
            "evaluation_cases": len(report["evaluation"]),
            "model": report["model"],
            "incremental": report["incremental"],
            "llm": report["llm"],
        },
        ensure_ascii=False,
        indent=2,
    )
)
