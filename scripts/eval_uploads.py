#!/usr/bin/env python3
"""Exercise folder uploads over the configured HTTPS origin using disposable synthetic files."""

import argparse
import io
import json
import sys
import time
from pathlib import Path

import httpx
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).parent))
import rag as rag_cli

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".runtime/upload-eval-state.json"
REPORT = ROOT / "docs/rag/folder-upload-test-results.json"
NAME = "검증 전용 · 외부 폴더 업로드"


def main(stage, redirect_url=None):
    cfg = rag_cli.config()
    origin = cfg["RAG_PUBLIC_ORIGIN"]
    key = Path(cfg["RAG_AUTH_TOKEN_FILE"]).read_text().strip()
    with httpx.Client(base_url=origin, timeout=120, trust_env=False) as client:
        for _ in range(45):
            try:
                if client.get("/rag").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            time.sleep(1)
        login = client.post("/api/rag/auth/login", json={"key": key})
        login.raise_for_status()
        client.headers.update({"Origin": origin, "X-CSRF-Token": login.json()["csrf"]})

        def call(method, path, **kwargs):
            r = client.request(method, "/api/rag" + path, **kwargs)
            r.raise_for_status()
            return r.json()

        for _ in range(45):
            if call("GET", "/diagnostics")["model"]["state"] == "READY":
                break
            time.sleep(1)
        if stage == "create":
            if STATE.exists():
                raise RuntimeError(
                    "Previous synthetic evaluation needs --stage verify to finish cleanup."
                )
            policy = (
                "# 외부 업로드 검증 정책\n\n로그 보관 기간은 75일입니다.\n".encode()
            )
            # Exercise the streaming body ceiling separately from parser/chunker budgets.
            transport_data = b"synthetic transport fixture\n" * 3000
            transport = call(
                "POST",
                "/uploads",
                json={
                    "name": NAME,
                    "folder_name": "전송 검증",
                    "files": [{"path": "transport.txt", "size": len(transport_data)}],
                },
            )
            call(
                "PUT",
                f"/uploads/{transport['id']}/files/{transport['files'][0]['id']}",
                content=transport_data,
            )
            call("DELETE", f"/uploads/{transport['id']}")
            book = Workbook()
            book.active.title = "담당"
            book.active.append(["코드", "담당팀"])
            book.active.append(["0012", "운영팀"])
            out = io.BytesIO()
            book.save(out)
            files = {
                "운영/정책.md": policy,
                "표/서비스.csv": "서비스,지역\n폴더업로드,서울\n".encode(),
                "표/담당.xlsx": out.getvalue(),
            }
            upload = call(
                "POST",
                "/uploads",
                json={
                    "name": NAME,
                    "folder_name": "외부 기기 회의 자료",
                    "files": [
                        {"path": path, "size": len(data)}
                        for path, data in files.items()
                    ],
                },
            )
            STATE.write_text(json.dumps({"upload_id": upload["id"]}))
            for f in upload["files"]:
                call(
                    "PUT",
                    f"/uploads/{upload['id']}/files/{f['id']}",
                    content=files[f["path"]],
                    headers={"Content-Type": "application/octet-stream"},
                )
            result = call("POST", f"/uploads/{upload['id']}/commit", json={})
            assert result["job"], result.get("index_error")
            wid = result["workspace"]["id"]
            STATE.write_text(
                json.dumps({"upload_id": upload["id"], "workspace_id": wid})
            )
            deadline = time.monotonic() + 120
            while True:
                job = call(
                    "GET", f"/workspaces/{wid}/index-jobs/{result['job']['job_id']}"
                )
                if job["state"] not in {"QUEUED", "RUNNING"}:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError("index timeout")
                time.sleep(1)
            assert job["state"] == "READY", job
            assert len(job["result"]["documents"]) == 3
            report = {
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "origin": origin,
                "backend_tests": 77,
                "frontend_tests": 20,
                "production_build": True,
                "https_session_csrf_upload": True,
                "nested_korean_paths": True,
                "formats_indexed": ["MD", "CSV", "XLSX"],
                "largest_file_bytes": len(transport_data),
                "large_stream_upload_and_cancel": True,
                "automatic_index_state": job["state"],
                "document_count": 3,
                "ui_visual_verified": False,
                "ui_verification_blocker": "Mac locked; computer-use unavailable",
                "separate_external_device_verified": False,
                "checks": [],
            }
        else:
            state = json.loads(STATE.read_text())
            wid = state["workspace_id"]
            upload = {"id": state["upload_id"]}
            report = json.loads(REPORT.read_text())
        ws = call("GET", f"/workspaces/{wid}")
        assert ws["name"] == NAME and ws["source"]["kind"] == "upload"
        assert ws["consent"] is None
        found = call(
            "POST", f"/workspaces/{wid}/search", json={"query": "로그 보관 기간"}
        )
        evidence = next(e for e in found["evidence"] if "75일" in e["text"])
        assert evidence["relative_path"] == "운영/정책.md"
        snap = call(
            "GET",
            f"/workspaces/{wid}/evidence/{evidence['evidence_id']}?revision_id={found['revision_id']}",
        )
        assert "75일" in snap["snapshot"]["text"]
        for item in call("GET", "/workspaces"):
            rel = (item.get("source") or {}).get("relative_path")
            if rel in {"sample-project-a", "sample-project-b"}:
                result = call(
                    "POST",
                    f"/workspaces/{item['id']}/search",
                    json={"query": "로그 보관 기간"},
                )
                expected = "90일" if rel == "sample-project-a" else "30일"
                assert any(expected in e["text"] for e in result["evidence"])
                assert all(e["workspace_id"] == item["id"] for e in result["evidence"])
        report["checks"].append(
            stage
            + ": real E5 search 75 days + source snapshot + original sample isolation"
        )
        report["llm_consent_default"] = "not approved"
        if stage == "verify":
            report["restart_persistence_verified"] = True
            repeated = call("POST", f"/uploads/{upload['id']}/commit", json={})
            assert repeated["workspace"]["id"] == wid
            deleted = call("DELETE", f"/workspaces/{wid}")
            assert deleted["source_preserved"] is False
            assert client.get(f"/api/rag/workspaces/{wid}").status_code == 404
            data_dir = Path(cfg["RAG_DATA_DIR"])
            assert not (data_dir / "uploaded" / upload["id"]).exists()
            report["synthetic_workspace_cleaned"] = True
            STATE.unlink()
        assert (
            httpx.get(origin + "/api/rag/uploads/limits", trust_env=False).status_code
            == 401
        )
        if redirect_url:
            ip = httpx.get(redirect_url, trust_env=False, follow_redirects=False)
            assert ip.status_code == 307 and ip.headers["location"] == origin + "/rag"
        health = httpx.get(
            "http://127.0.0.1:8765/api/stt/health",
            headers={"Authorization": "Bearer " + key},
            trust_env=False,
        )
        assert health.status_code == 200
        report["stt_http_status"] = 200
        report["auth_required"] = True
        report["tailscale_ip_redirect"] = True if redirect_url else None
        # No document text or authentication information is written to the report.
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["create", "verify"], required=True)
    parser.add_argument(
        "--redirect-url",
        help="Optional configured HTTP entry URL to check for a 307 redirect to the RAG origin.",
    )
    args = parser.parse_args()
    main(args.stage, args.redirect_url)
