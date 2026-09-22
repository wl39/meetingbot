"""Check the installed priority pipeline against synthetic documents with its real LLM.

Run after the new services are deployed:
    backend/.venv/bin/python scripts/meeting_priority_smoke.py

Only a newly created temporary workspace and its policy/consent are changed. Global
AI settings and existing workspaces are read-only. Failures are written to the JSON
report before exit; this script never substitutes fake inference for a live check.
"""

import argparse
import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SUPERSEDED"}
DOCUMENTS = {
    "logs.md": """# 합성 검증 자료: 우리 서비스 운영 로그 정책
우리 서비스의 운영서버 로그 보관 기간은 90일입니다.
우리 서비스의 개발서버 로그 보관 기간은 30일입니다.
운영 로그는 중앙 로그 저장소에서 관리합니다. 로그 보관 정책을 설명할 때 운영/개발 환경을 구분합니다.
""",
    "docker.md": """# 합성 검증 자료: 우리 서비스 Docker 배포와 이미지 관리
우리 서비스의 Docker 이미지는 사내 컨테이너 레지스트리에 저장합니다.
이미지에는 배포 버전과 Git 커밋 해시를 태그로 붙입니다.
운영에 배포 중인 이미지는 삭제하지 않습니다. 배포에 쓰이지 않는 이미지는 30일 후 정리합니다.
개인 프로젝트의 이미지 관리는 우리 서비스 정책의 적용 대상이 아닙니다.
""",
}
CASES = [
    {"name": "filler", "text": "어", "score": 1, "queue": None, "context": []},
    {"name": "weather", "text": "밖에 비 와요?", "score": 2, "queue": None, "context": []},
    {"name": "topic", "text": "저희 운영 로그 이야기해야 해요.", "score": 3, "queue": "SQ",
     "context": ["지금부터 우리 서비스 운영 정책 회의를 시작합니다."]},
    {"name": "log_claim", "text": "우리 운영서버 로그 보관일은 45일이에요.", "score": 4, "queue": "PQ",
     "context": ["우리 서비스 운영서버의 로그 보관 정책을 검토하고 있어요."]},
    {"name": "docker_service", "text": "도커 이미지 관리 어떻게 하세요?", "score": 4, "queue": "PQ",
     "context": ["우리 서비스의 운영 배포 과정에 관해 말씀드리고 있어요.", "우리 운영 레지스트리 이야기입니다."]},
    {"name": "docker_personal", "text": "도커 이미지 관리 어떻게 하세요?", "score": 2, "queue": None,
     "context": ["주말에 취미로 개인 프로젝트를 만들고 있어요.", "회사 서비스와는 관계없는 개인 개발 이야기예요."]},
    {"name": "ai_request", "text": "AI야, 우리 운영서버 로그 보관일 좀 알려줘.", "score": 5, "queue": "PQ",
     "context": ["우리 서비스 운영서버 정책을 확인하고 있어요."], "addressed_to_ai": True},
]


class SmokeError(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, origin, token):
        target = urlsplit(origin)
        if (target.scheme != "http" or target.hostname not in {"127.0.0.1", "localhost", "::1"}
                or target.username or target.password or target.query or target.fragment
                or target.path.rstrip("/") != "/api/rag" or target.port is None):
            raise SmokeError("LOOPBACK_RAG_ORIGIN_REQUIRED")
        self.origin, self.token = origin.rstrip("/"), token
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def api(self, path, body=None, method=None, internal=False):
        raw = body if isinstance(body, bytes) else (
            json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
        headers = {"Authorization": "Bearer " + self.token,
                   "Content-Type": "application/octet-stream" if isinstance(body, bytes) else "application/json"}
        if internal:
            headers["X-Meeting-Subscription"] = "1"
        request = Request(self.origin + path, data=raw, method=method or ("POST" if raw is not None else "GET"),
                          headers=headers)
        try:
            with self.opener.open(request, timeout=50) as response:
                raw_response = response.read(4 * 1024 * 1024 + 1)
                if len(raw_response) > 4 * 1024 * 1024:
                    raise SmokeError("RESPONSE_TOO_LARGE")
                return json.loads(raw_response) if raw_response else None
        except HTTPError as error:
            code = "HTTP_REQUEST_FAILED"
            try:
                value = json.loads(error.read(65536)).get("error_code", code)
                if isinstance(value, str) and len(value) <= 100 and value.replace("_", "").isalnum():
                    code = value
            except (ValueError, UnicodeError, AttributeError):
                pass
            raise SmokeError(code, error.code) from None
        except TimeoutError:
            raise SmokeError("REQUEST_TIMEOUT") from None
        except URLError:
            raise SmokeError("SERVICE_UNAVAILABLE") from None


def safe_error(error):
    return {"code": error.code, "http_status": error.status} if isinstance(error, SmokeError) else {
        "code": type(error).__name__}


def wait_until(read, finished, seconds):
    deadline = time.monotonic() + seconds
    while True:
        value = read()
        if finished(value):
            return value
        if time.monotonic() >= deadline:
            raise SmokeError("PROCESSING_TIMEOUT")
        time.sleep(1)


def evaluate(case, job, model):
    classification = job.get("classification") or {}
    result = job.get("result") or {}
    timings = classification.get("timings_ms") or {}
    result_timings = result.get("timings_ms") or {}
    received, deadline = job.get("received_at"), job.get("deadline_at")
    numeric = isinstance(received, (int, float)) and isinstance(deadline, (int, float))
    classification_time = timings.get("classification")
    checks = {
        "completed": job.get("state") == "COMPLETED",
        "score": job.get("score") == case["score"],
        "queue": job.get("queue_class") == case["queue"],
        "observed_filter_model": classification.get("model") == model,
        "deadline_is_20_seconds": bool(numeric and math.isclose(deadline - received, 20, abs_tol=0.01)),
        "classification_timing_recorded": isinstance(classification_time, (int, float)) and classification_time >= 0,
    }
    if case["score"] >= 3:
        checks["grounded_result"] = result.get("status") == "popup" and bool((result.get("popup") or {}).get("citations"))
        checks["rag_timing_recorded"] = all(isinstance(result_timings.get(key), (int, float))
                                            and result_timings[key] >= 0 for key in ("retrieval", "generation", "total"))
    else:
        checks["no_rag_result"] = result.get("status") == "suppressed" and not result.get("popup") \
            and job.get("queue_class") is None
    if case["queue"] == "PQ":
        checks["deadline_met"] = not job.get("deadline_missed") and numeric and job.get("updated_at", math.inf) <= deadline
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="http://127.0.0.1:8766/api/rag")
    parser.add_argument("--token-file", type=Path, default=ROOT / ".runtime/local-token")
    parser.add_argument("--report", type=Path, default=ROOT / "docs/meeting-priority-live-results.json")
    parser.add_argument("--case-timeout", type=int, default=120)
    args = parser.parse_args(argv)
    report = {"synthetic": True, "live_llm": True, "started_at": datetime.now(timezone.utc).isoformat(),
              "passed": False, "cases": [], "checks": [], "errors": [], "cleanup": {"completed": False}}
    client = wid = upload_id = None
    global_version = None
    try:
        client = Client(args.origin, args.token_file.expanduser().read_text().strip())
        identity = client.api("/auth/session")
        if identity.get("role") != "superadmin":
            raise SmokeError("SUPERADMIN_REQUIRED")
        diagnostic = wait_until(lambda: client.api("/diagnostics"),
                                lambda d: d["model"]["state"] == "READY", 60)
        if not diagnostic["llm"].get("global_allowed") or not diagnostic["llm"].get("configured"):
            raise SmokeError("EXISTING_AI_CONFIGURATION_REQUIRED")
        settings = client.api("/llm/settings")
        global_version = settings["version"]
        model = settings.get("default_model") or diagnostic["llm"].get("model")
        if not model:
            raise SmokeError("EXISTING_MODEL_REQUIRED")
        report.update(observed_model=model, global_settings_version=global_version,
                      embedding_model=diagnostic["model"].get("model"))
        upload = client.api("/uploads", {
            "name": "Priority Queue 임시 합성 검증 " + uuid.uuid4().hex[:8], "folder_name": "priority-synthetic",
            "description": "실제 모델 분류와 영속 큐 검증 후 삭제하는 합성 문서",
            "files": [{"path": name, "size": len(text.encode())} for name, text in DOCUMENTS.items()],
        })
        upload_id = upload["id"]
        for file in upload["files"]:
            client.api(f"/uploads/{upload_id}/files/{file['id']}", DOCUMENTS[file["path"]].encode(), "PUT")
        committed = client.api(f"/uploads/{upload_id}/commit", {})
        wid, jid = committed["workspace"]["id"], committed["job"]["job_id"]
        report["temporary_workspace_id"] = wid
        indexed = wait_until(lambda: client.api(f"/workspaces/{wid}/index-jobs/{jid}"),
                             lambda job: job["state"] not in {"QUEUED", "RUNNING"}, 120)
        if indexed["state"] != "READY":
            raise SmokeError("SYNTHETIC_INDEX_FAILED")
        client.api(f"/workspaces/{wid}", {"external_llm_approved": True,
                   "provider_id": diagnostic["llm"]["provider_id"]}, "PATCH")
        policy = client.api(f"/workspaces/{wid}/meeting/policy")
        version = policy.pop("version")
        policy.update(expected_version=version, priority_response_target_seconds=20, filter_model=model,
                      scope_profile={"description": "우리 서비스의 운영 로그와 Docker 배포 및 이미지 관리 정책",
                                     "included_topics": ["우리 서비스 운영 로그", "우리 서비스 Docker 배포", "운영 레지스트리"],
                                     "excluded_topics": ["개인 프로젝트", "날씨", "일상 대화"],
                                     "aliases": ["운영서버", "우리 서비스", "운영 인프라"]})
        report["temporary_policy"] = client.api(f"/workspaces/{wid}/meeting/policy", policy, "PUT")
        report["checks"].append("synthetic workspace indexed, isolated consent and priority policy configured")
        for case in CASES:
            record = {"name": case["name"], "input": case["text"], "context": case["context"],
                      "expected_score": case["score"], "expected_queue": case["queue"], "passed": False}
            started = time.monotonic()
            try:
                sid = "synthetic-priority-" + uuid.uuid4().hex
                utterance_id = "synthetic-" + case["name"]
                grant = client.api(f"/workspaces/{wid}/meeting/sessions/{sid}/subscription",
                                   {"enabled": True, "revision_id": indexed["revision_id"]})
                client.api(f"/workspaces/{wid}/meeting/sessions/{sid}/sync",
                           {"utterance_ids": [utterance_id], "generation": 1}, internal=True)
                body = {"session_id": sid, "utterance": {"utterance_id": utterance_id, "revision": 1,
                        "text": case["text"], "status": "stable", "speaker_id": "synthetic-A", "start_ms": 1000,
                        "end_ms": 5000}, "context": [{"text": text, "speaker_id": "synthetic-B"}
                                                      for text in case["context"]], "following_context": [],
                        "revision_id": grant["revision_id"], "origin": "live", "source_generation": 1,
                        "addressed_to_ai": case.get("addressed_to_ai", False), "received_at": time.time(),
                        "source_key": hashlib.sha256((sid + case["name"]).encode()).hexdigest()}
                accepted = client.api(f"/workspaces/{wid}/meeting/jobs", body, internal=True)
                record["job_id"] = accepted["id"]

                def read(case_sid=sid, case_jid=accepted["id"], case_record=record):
                    page = client.api(f"/workspaces/{wid}/meeting/jobs?{urlencode({'session_id': case_sid, 'limit': 15})}")
                    observed = next((job for job in page["jobs"] if job["id"] == case_jid), {})
                    case_record["last_observation"] = {key: observed.get(key) for key in
                                                  ("state", "stage", "score", "queue_class", "reason", "deadline_missed")}
                    return observed

                job = wait_until(read, lambda value: value.get("state") in TERMINAL, args.case_timeout)
                checks = evaluate(case, job, model)
                record.update(score=job.get("score"), queue=job.get("queue_class"), state=job.get("state"),
                              status=(job.get("result") or {}).get("status"), reason=job.get("reason"),
                              received_at=job.get("received_at"), deadline_at=job.get("deadline_at"),
                              completed_at=job.get("updated_at"), deadline_missed=job.get("deadline_missed"),
                              classification=job.get("classification"), result=job.get("result"),
                              elapsed_seconds=round(time.monotonic() - started, 3), checks=checks,
                              passed=all(checks.values()))
            except Exception as error:  # noqa: BLE001 -- each live failure must be captured before continuing.
                record.update(error=safe_error(error), elapsed_seconds=round(time.monotonic() - started, 3))
            report["cases"].append(record)
            print(json.dumps({k: record.get(k) for k in ("name", "score", "queue", "state", "status",
                                                        "deadline_missed", "passed", "error")}, ensure_ascii=False), flush=True)
        report["global_settings_unchanged"] = client.api("/llm/settings")["version"] == global_version
        report["passed"] = len(report["cases"]) == len(CASES) and all(c["passed"] for c in report["cases"]) \
            and report["global_settings_unchanged"]
    except Exception as error:  # noqa: BLE001 -- preserve a report even for setup or protocol failures.
        report["errors"].append(safe_error(error))
    finally:
        try:
            if wid:
                client.api(f"/workspaces/{wid}", method="DELETE")
            elif upload_id:
                client.api(f"/uploads/{upload_id}", method="DELETE")
            report["cleanup"]["completed"] = True
        except Exception as error:  # noqa: BLE001 -- cleanup failures must not prevent saving the report.
            report["cleanup"]["error"] = safe_error(error)
            report["passed"] = False
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"Synthetic live queue report: {args.report}", flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
