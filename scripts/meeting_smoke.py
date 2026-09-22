"""Exercise the installed meeting LLM/RAG pipeline with a temporary synthetic workspace.

Uses the existing enabled AI configuration; never changes global settings or existing workspaces.
Run: backend/.venv/bin/python scripts/meeting_smoke.py
"""

import json
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
TOKEN = (ROOT / ".runtime/local-token").read_text().strip()
ORIGIN = "http://127.0.0.1:8766/api/rag"


def api(path, body=None, method=None):
    raw = body if isinstance(body, bytes) else (json.dumps(body).encode() if body is not None else None)
    request = Request(
        ORIGIN + path, data=raw, method=method or ("POST" if raw is not None else "GET"),
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/octet-stream" if isinstance(body, bytes) else "application/json"},
    )
    with urlopen(request, timeout=50) as response:
        return json.load(response)


documents = {
    "logs.md": """# 합성 회의 검증 정책 — 로그 기록
확정된 현행 정책: 운영서버 로그 기록은 90일 동안 서버에 보관합니다.
개발서버 로그 기록은 30일 동안 서버에 보관합니다.
운영서버와 개발서버의 보관 기간은 다릅니다.
""",
    "access.md": """# 합성 회의 검증 정책 — 운영서버 접속
운영서버에 접속할 때는 개인키가 반드시 필요합니다.
개인키 발급 절차는 사내 포털의 보안 > 서버 접근 메뉴에서 확인할 수 있습니다.
개인키는 보안 담당자 김가상 님을 통해 발급받을 수 있습니다.
개인키 원문은 공유하거나 회의 화면에 표시하지 않습니다.
""",
    "backup.md": """# 합성 회의 검증 정책 — 운영서버 백업
운영서버 백업은 매일 오전 2시에 자동 실행됩니다.
백업 파일은 14일 동안 보관합니다. 복구 요청은 플랫폼팀에서 접수합니다.
""",
}
cases = [
    ("correction", "운영서버 로그 기록은 45일 동안 서버에 남아요.", "warning"),
    ("guidance", "운영서버 접속할 때는 꼭 개인키 필요해요.", "caution"),
    ("confirmation", "운영서버 로그 기록은 90일 동안 보관됩니다.", "success"),
    ("information", "운영서버 백업 일정은 어떻게 되나요?", "info"),
    ("missing", "내년 달 기지에 배치할 양자 로봇 수는 몇 대인가요?", None),
    ("smalltalk", "안녕하세요. 오늘 와 주셔서 감사합니다.", None),
]


def main():
    report = {"synthetic": True, "live_llm": True, "checks": [], "cases": []}
    wid = upload_id = None
    try:
        ready_deadline = time.monotonic() + 60
        diagnostic = None
        while time.monotonic() < ready_deadline:
            try:
                diagnostic = api("/diagnostics")
                if diagnostic["model"]["state"] == "READY":
                    break
            except URLError:
                pass  # Only retry this read while launchd is starting the service.
            time.sleep(0.5)
        assert diagnostic and diagnostic["model"]["state"] == "READY", "RAG did not become ready"
        assert diagnostic["llm"]["global_allowed"] and diagnostic["llm"]["configured"], "Existing AI must be enabled"
        report["model"] = diagnostic["llm"]["model"]
        upload = api("/uploads", {
            "name": "회의 도우미 임시 합성 검증 " + uuid.uuid4().hex[:6],
            "folder_name": "meeting-synthetic",
            "description": "자동 검증 후 삭제하는 합성 정책 자료",
            "files": [{"path": name, "size": len(content.encode())} for name, content in documents.items()],
        })
        upload_id = upload["id"]
        for file in upload["files"]:
            api(f"/uploads/{upload_id}/files/{file['id']}", documents[file["path"]].encode(), "PUT")
        committed = api(f"/uploads/{upload_id}/commit", {})
        wid = committed["workspace"]["id"]
        job_id = committed["job"]["job_id"]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = api(f"/workspaces/{wid}/index-jobs/{job_id}")
            if job["state"] not in {"QUEUED", "RUNNING"}:
                break
            time.sleep(0.5)
        assert job["state"] == "READY", job
        api(f"/workspaces/{wid}", {"external_llm_approved": True,
                                   "provider_id": diagnostic["llm"]["provider_id"]}, "PATCH")
        report["checks"].append("temporary synthetic documents indexed with real E5 and isolated consent")
        for name, statement, expected in cases:
            response = api(f"/workspaces/{wid}/meeting/analyze", {
                "session_id": "synthetic-meeting", "utterance": {
                    "utterance_id": "synthetic-" + name, "revision": 1, "text": statement,
                    "status": "stable", "speaker_id": "A", "start_ms": 1000, "end_ms": 5000,
                }, "context": [],
            })
            popup = response.get("popup")
            case = {"name": name, "input": statement, "expected_kind": expected,
                    "status": response["status"], "reason": response.get("reason"),
                    "analysis": response.get("analysis"), "popup": popup,
                    "timings_ms": response["timings_ms"]}
            case["passed"] = (popup is not None and popup["kind"] == expected) if expected else (
                popup is None and response["status"] in {"suppressed", "insufficient_evidence"})
            if popup:
                assert all(e["workspace_id"] == wid for e in response["evidence"])
                assert set(popup["citations"]) <= {e["evidence_id"] for e in response["evidence"]}
            report["cases"].append(case)
            print(json.dumps(case, ensure_ascii=False), flush=True)
        report["passed"] = all(c["passed"] for c in report["cases"])
    finally:
        if wid:
            api(f"/workspaces/{wid}", method="DELETE")
            report["checks"].append("temporary workspace and uploaded synthetic files deleted")
        elif upload_id:
            api(f"/uploads/{upload_id}", method="DELETE")
        (ROOT / "docs/meeting-live-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    assert report["passed"], "Check docs/meeting-live-results.json for actual model classifications"


if __name__ == "__main__":
    main()
