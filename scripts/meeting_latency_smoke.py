"""Measure the deployed durable meeting pipeline with one synthetic spoken claim.

Run only after deployment: backend/.venv/bin/python scripts/meeting_latency_smoke.py
Uses macOS speech synthesis, not a physical microphone. Existing records, workspaces,
global model/reasoning settings and existing meeting policies are never changed.
Only the new temporary workspace's consent and topic scope are configured to match
its synthetic policy documents; all other policy fields keep their current values.
The existing enabled AI provider processes only this newly created synthetic fixture.

Only this run's temporary IDs are queried in SQLite, in read-only mode: the public
jobs API hides superseded jobs and cannot confirm deletion of a subscription receipt.
Observations are sampled every 0.5 seconds; they are not exact server event timestamps.
"""

# Always preserve a sanitized report and release temporary resources on any failure.
# ruff: noqa: BLE001

import argparse
import asyncio
import json
import os
import re
import shlex
import sqlite3
import tempfile
import time
import uuid
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".runtime/meeting-latency-qa/live-smoke.json"
POLL_SECONDS = 0.5
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SUPERSEDED"}
STABLE = {"stable", "corrected", "final"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def data_directory(prefix, env_file, fallback):
    key = prefix + "_DATA_DIR"
    configured = os.environ.get(key)
    if configured is None and env_file.is_file():
        for line in env_file.read_text().splitlines():
            name, separator, value = line.strip().removeprefix("export ").partition("=")
            if separator and name.strip() == key:
                values = shlex.split(value, comments=True)
                configured = values[0] if values else None
    return Path(configured).expanduser() if configured else fallback


def read_rows(path, query, params):
    # mode=ro refuses missing databases; no application initialization or migrations.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        return [dict(row) for row in db.execute(query, params)]


def job_metadata(path, wid, sid):
    rows = read_rows(
        path,
        "SELECT id,utterance_id,utterance_revision,source_key,state,stage,reason,score,queue_class,"
        "created_at,updated_at,received_at,deadline_at,deadline_missed,attempts,"
        "json_extract(classification,'$.timings_ms') AS classification_timings_ms,"
        "json_extract(classification,'$.model') AS classification_model,"
        "json_extract(result,'$.timings_ms') AS result_timings_ms,"
        "json_extract(result,'$.status') AS result_status "
        "FROM meeting_jobs WHERE workspace_id=? AND session_id=? ORDER BY created_at,id",
        (wid, sid),
    )
    for row in rows:
        for key in ("classification_timings_ms", "result_timings_ms"):
            row[key] = json.loads(row[key]) if row[key] else None
    return rows


def cleanup_state(stt_db, rag_db, wid, sid):
    stt = read_rows(stt_db, "SELECT COUNT(*) AS count FROM meeting_subscriptions WHERE session_id=?", (sid,))
    jobs = read_rows(rag_db, "SELECT COUNT(*) AS count FROM meeting_jobs WHERE workspace_id=? AND session_id=?", (wid, sid))
    grants = read_rows(rag_db, "SELECT enabled FROM meeting_subscriptions WHERE workspace_id=? AND session_id=?", (wid, sid))
    return {
        "stt_subscription_receipts": stt[0]["count"],
        "rag_jobs": jobs[0]["count"],
        "rag_subscription_enabled": any(row["enabled"] for row in grants),
    }


def cleanup_finished(state):
    return not any(state.values())


def safe_error(error):
    # Never serialize request headers, response bodies, credential values or tracebacks.
    result = {"type": type(error).__name__}
    if isinstance(error, AssertionError):
        result["message"] = str(error)
    if isinstance(error, httpx.HTTPStatusError):
        result["http_status"] = error.response.status_code
    return result


def settings_summary(settings):
    return {key: settings.get(key) for key in ("version", "enabled", "default_model", "reasoning_effort")}


def observe_jobs(rows, seen, elapsed_ms):
    for job in rows:
        observed = seen.setdefault(job["id"], {"id": job["id"], "first_seen_ms": elapsed_ms, "transitions": []})
        transition = {"state": job["state"], "stage": job["stage"]}
        previous = observed["transitions"][-1] if observed["transitions"] else None
        if previous is None or any(previous[key] != value for key, value in transition.items()):
            observed["transitions"].append({**transition, "observed_ms": elapsed_ms})
        classification, result = job.get("classification"), job.get("result")
        observed["reason"] = job.get("reason")
        if classification:
            observed.setdefault("first_classification_ms", elapsed_ms)
            observed["classification_timings_ms"] = classification.get("timings_ms", {})
            observed["classification_model"] = classification.get("model")
        if result:
            observed.setdefault("first_result_ms", elapsed_ms)
            observed["result_timings_ms"] = result.get("timings_ms", {})
            observed["result_status"] = result.get("status")
            if result.get("status") == "popup" and result.get("popup"):
                observed.setdefault("first_popup_ms", elapsed_ms)


def validate_popup(rows, wid):
    candidates = [job for job in rows if (job.get("result") or {}).get("status") == "popup"]
    require(bool(candidates), "No popup for the synthetic 45-day policy claim")
    for job in candidates:
        result = job["result"]
        popup = result.get("popup") or {}
        sources = {source["evidence_id"]: source for source in result.get("evidence", [])}
        citations = popup.get("citations", [])
        if not re.search(r"90\s*일", popup.get("message", "")):
            continue
        require(bool(citations) and set(citations) <= sources.keys(), "Popup citations do not resolve to evidence")
        require(all(source["workspace_id"] == wid for source in sources.values()), "Popup includes evidence outside the synthetic workspace")
        cited = [sources[eid]["text"] for eid in citations]
        require(any(re.search(r"90\s*일", text) for text in cited), "Popup does not cite the 90-day synthetic policy")
        return {"job_id": job["id"], "popup": popup, "cited_source_text": cited, "citation_count": len(citations)}
    raise AssertionError("Popup omitted the 90-day policy correction")


async def observe_pipeline(client, api, stt, sid, wid, stream, started, report):
    seen = {}
    last_signature = None
    changed_at = started
    next_poll = started
    previous_poll = None
    poll_gaps = []
    poll_count = 0
    report["observed_jobs"] = seen

    async def timed_session():
        session = await api(client, stt, f"/sessions/{sid}")
        return session, round((time.monotonic() - started) * 1000)

    async def timed_jobs():
        rows, cursor = [], None
        for _ in range(20):
            path = f"/meeting/sessions/{sid}/jobs?workspace_id={wid}&limit=50"
            if cursor:
                path += "&cursor=" + quote(cursor, safe="")
            payload = await api(client, stt, path)
            rows.extend(payload["jobs"])
            cursor = payload.get("next_cursor")
            if not cursor:
                return rows, round((time.monotonic() - started) * 1000)
        raise AssertionError("Unexpected job pagination volume for one synthetic phrase")

    try:
        async with asyncio.timeout(210):
            while True:
                if stream.done():
                    stream.result()  # Surface stream failures without waiting for the poll deadline.
                now = time.monotonic()
                if previous_poll is not None:
                    poll_gaps.append(round((now - previous_poll) * 1000))
                previous_poll = now
                (session, session_ms), (rows, jobs_ms) = await asyncio.gather(timed_session(), timed_jobs())
                poll_count += 1
                stable = [u for u in session["utterances"] if u["status"] in STABLE]
                if stable:
                    report.setdefault("first_stable_ms", session_ms)
                observe_jobs(rows, seen, jobs_ms)
                for key in ("first_classification_ms", "first_result_ms", "first_popup_ms"):
                    values = [job[key] for job in seen.values() if key in job]
                    if values:
                        report[key] = min(values)
                signature = (
                    tuple((u["utterance_id"], u["revision"], u["status"], u["text"]) for u in session["utterances"]),
                    tuple((job["id"], job["state"], job["stage"], job["updated_at"]) for job in rows),
                )
                if signature != last_signature:
                    last_signature, changed_at = signature, time.monotonic()
                if stream.done() and session["state"] == "COMPLETED" and rows and all(job["state"] in TERMINAL for job in rows) and time.monotonic() - changed_at >= 3:
                    return session, rows
                require(session["state"] not in {"FAILED", "CANCELLED", "INTERRUPTED"}, "Synthetic transcription ended unsuccessfully")
                next_poll += POLL_SECONDS
                # Do not burst requests to catch up after a slow response.
                next_poll = max(next_poll, time.monotonic())
                await asyncio.sleep(max(0, next_poll - time.monotonic()))
    finally:
        report["polling"] = {
            "target_interval_ms": 500,
            "poll_count": poll_count,
            "max_actual_gap_ms": max(poll_gaps, default=None),
            "mean_actual_gap_ms": round(sum(poll_gaps) / len(poll_gaps)) if poll_gaps else None,
            "timing_basis": "Client monotonic milliseconds from WebSocket task start; includes polling/network delay",
        }


async def run(args):
    # Reuse the existing paced PCM producer and fixture; importing these does not run them.
    from meeting_smoke import documents
    from meeting_stream_smoke import PHRASE, RAG, STT, api, stream_audio, synthesize

    token = (ROOT / ".runtime/local-token").read_text().strip()
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "synthetic": True,
        "physical_microphone": False,
        "fixture": "One macOS Yuna synthetic Korean phrase, paced 16 kHz mono PCM WebSocket input",
        "spoken_text": PHRASE,
        "pipeline": "durable subscription enabled before real-time PCM -> stable STT -> classification -> RAG result",
        "passed": False,
        "checks": [],
        "cleanup": {},
    }
    sid = wid = upload_id = None
    stream = None
    temporary = None
    settings_before = None
    started = time.monotonic()
    async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=30, trust_env=False, follow_redirects=False) as client:
        async def idle_health():
            health = await api(client, STT, "/health")
            require(health["active_session"] is None, "An existing active session prevents this smoke test")
            require(not health.get("management_busy"), "STT model management is busy")
            return health

        try:
            async with asyncio.timeout(400):
                health = await idle_health()  # First API, before any resource creation or synthesis.
                require(health["engine"] == "real", "The deployed STT must use real models")
                require(args.stt_db.is_file() and args.rag_db.is_file(), "Read-only metadata database paths are unavailable; use --stt-db/--rag-db")
                deadline = time.monotonic() + 75
                while not all(health["workers"].get(key, {}).get("ready") for key in ("asr", "vad")):
                    require(time.monotonic() < deadline, "Real STT workers did not become ready")
                    await asyncio.sleep(POLL_SECONDS)
                    health = await idle_health()
                diagnostic = await api(client, STT, "/meeting/diagnostics")
                require(diagnostic["model"]["state"] == "READY", "Real RAG embedding model is unavailable")
                require(diagnostic["llm"]["global_allowed"] and diagnostic["llm"]["configured"], "Existing global AI configuration must already be enabled")
                settings_before = settings_summary(await api(client, RAG, "/llm/settings"))
                report["llm_settings_before"] = settings_before
                report["checks"].append("no active session before starting; existing AI configuration read only")
                temporary = tempfile.TemporaryDirectory(prefix="meeting-latency-synthetic-")
                audio = await asyncio.to_thread(synthesize, Path(temporary.name))
                report["audio_seconds"] = round(len(audio) / 16000, 3)
                await idle_health()
                upload = await api(client, RAG, "/uploads", {
                    "name": "지연 측정 임시 합성 검증 " + uuid.uuid4().hex[:8],
                    "folder_name": "meeting-latency-synthetic",
                    "description": "자동 지연 검증 후 삭제하는 합성 정책 자료",
                    "files": [{"path": name, "size": len(content.encode())} for name, content in documents.items()],
                })
                upload_id = upload["id"]
                for file in upload["files"]:
                    await api(client, RAG, f"/uploads/{upload_id}/files/{file['id']}", documents[file["path"]].encode(), "PUT")
                committed = await api(client, RAG, f"/uploads/{upload_id}/commit", {})
                wid, index_id = committed["workspace"]["id"], committed["job"]["job_id"]
                report["temporary_workspace_id"] = wid
                deadline = time.monotonic() + 90
                while True:
                    index = await api(client, RAG, f"/workspaces/{wid}/index-jobs/{index_id}")
                    if index["state"] not in {"QUEUED", "RUNNING"}:
                        break
                    require(time.monotonic() < deadline, "Synthetic document indexing timed out")
                    await asyncio.sleep(POLL_SECONDS)
                require(index["state"] == "READY", "Synthetic documents failed to index")
                await idle_health()
                await api(client, RAG, f"/workspaces/{wid}", {"external_llm_approved": True, "provider_id": diagnostic["llm"]["provider_id"]}, "PATCH")
                policy_path = f"/workspaces/{wid}/meeting/policy"
                policy = await api(client, RAG, policy_path)
                policy_update = {key: value for key, value in policy.items() if key != "version"}
                policy_update["expected_version"] = policy["version"]
                policy_update["scope_profile"] = {
                    **policy["scope_profile"],
                    "description": "운영서버와 개발서버의 로그 보관, 서버 접속 및 백업 정책을 확인하는 회의",
                    "included_topics": ["운영서버 로그 보관 기간", "개발서버 로그 보관 기간", "운영서버 개인키 접속", "운영서버 백업 및 복구"],
                    "aliases": ["운영 서버", "개발 서버", "로그 기록", "서버 보관 기간"],
                }
                report["temporary_policy"] = await api(client, RAG, policy_path, policy_update, "PUT")
                report["checks"].append("only the new synthetic workspace topic scope configured; scheduling and model fields preserved")
                health = await idle_health()
                available = health["workers"]["asr"].get("models", {})
                model = "large-v3-turbo" if available.get("large-v3-turbo", {}).get("ready") else "small"
                session = await api(client, STT, "/sessions", {"model": model, "language": "ko", "num_speakers": 1, "retain_audio": False})
                sid = session["id"]
                report.update(temporary_session_id=sid, stt_model=model)
                subscription = await api(client, STT, f"/meeting/sessions/{sid}/subscription", {"workspace_id": wid, "revision_id": index["revision_id"], "enabled": True}, "PUT")
                require(subscription["enabled"] and subscription["workspace_id"] == wid, "Durable subscription was not enabled")
                # Verify the configured DB is the deployed DB, using only our new IDs.
                state = cleanup_state(args.stt_db, args.rag_db, wid, sid)
                require(state["stt_subscription_receipts"] == 1 and state["rag_subscription_enabled"], "Metadata database paths do not match the deployed services")
                await idle_health()
                report["checks"].append("own temporary workspace consent and durable subscription enabled before streaming")
                stream_started = time.monotonic()
                report["stream_timings"] = {}
                stream = asyncio.create_task(stream_audio(token, sid, audio, report["stream_timings"]))
                session, rows = await observe_pipeline(client, api, STT, sid, wid, stream, stream_started, report)
                snapshots, stream_ms = await stream
                report.update(stt_stream_ms=stream_ms, stt_state=session["state"], snapshot_count=len(snapshots), recognized_text=" ".join(u["text"] for u in session["utterances"]))
                report["stt_metrics"] = session.get("metrics", {})
                require(not session.get("audio_retained"), "Synthetic audio was unexpectedly retained")
                require(any(u["status"] in STABLE and "운영" in u["text"] and "로그" in u["text"] and re.search(r"45|사십\s*오", u["text"]) for u in session["utterances"]), "STT did not produce the stable synthetic production log claim")
                report["popup_validation"] = validate_popup(rows, wid)
                for key in ("first_classification_ms", "first_result_ms", "first_popup_ms"):
                    if key in report and "first_stable_ms" in report:
                        report[key.replace("_ms", "_after_first_stable_ms")] = report[key] - report["first_stable_ms"]
                report["checks"].append("durable pipeline produced a 90-day correction with citations to own synthetic documents")
                report["passed"] = True
        except Exception as error:
            report["error"] = safe_error(error)
        finally:
            if stream and not stream.done():
                stream.cancel()
            if stream:
                await asyncio.gather(stream, return_exceptions=True)
            if sid and wid:
                try:
                    metadata = job_metadata(args.rag_db, wid, sid)
                    observed = report.get("observed_jobs", {})
                    report["jobs"] = [{**observed.get(job["id"], {}), **job} for job in metadata]
                    # Retain observed stage timings even if supersession cleared the result.
                    for job in report["jobs"]:
                        history = observed.get(job["id"], {})
                        job["observed_classification_timings_ms"] = history.get("classification_timings_ms")
                        job["observed_result_timings_ms"] = history.get("result_timings_ms")
                    report["job_counts"] = {"total": len(metadata), "by_state": dict(Counter(job["state"] for job in metadata)), "superseded": sum(job["state"] == "SUPERSEDED" for job in metadata)}
                except Exception as error:
                    report["metadata_error"] = safe_error(error)
                    report["passed"] = False
            report.pop("observed_jobs", None)
            if sid:
                try:
                    await api(client, STT, f"/sessions/{sid}", method="DELETE")
                    response = await client.get(STT + f"/sessions/{sid}")
                    require(response.status_code == 404, "Own synthetic session was not deleted")
                    report["cleanup"]["session_deleted"] = True
                    deadline = time.monotonic() + 45
                    while wid:
                        state = cleanup_state(args.stt_db, args.rag_db, wid, sid)
                        report["cleanup"]["subscription_state"] = state
                        if cleanup_finished(state):
                            report["cleanup"]["subscription_cleanup_confirmed"] = True
                            break
                        require(time.monotonic() < deadline, "Durable subscription deletion was not acknowledged")
                        await asyncio.sleep(POLL_SECONDS)
                except Exception as error:
                    report["cleanup"]["session_or_subscription_error"] = safe_error(error)
                    report["passed"] = False
            # Always clean our workspace, even if a failed bridge prevents receipt confirmation.
            # The report distinguishes this fallback from successful ordered cleanup.
            if wid or upload_id:
                try:
                    path = f"/workspaces/{wid}" if wid else f"/uploads/{upload_id}"
                    await api(client, RAG, path, method="DELETE")
                    report["cleanup"]["workspace_deleted" if wid else "upload_deleted"] = True
                    if sid and not report["cleanup"].get("subscription_cleanup_confirmed"):
                        report["cleanup"]["workspace_delete_after_cleanup_failure"] = True
                except Exception as error:
                    report["cleanup"]["workspace_error"] = safe_error(error)
                    report["passed"] = False
            if temporary:
                temporary.cleanup()
                report["cleanup"]["synthetic_audio_files_deleted"] = True
            if settings_before is not None:
                try:
                    after = settings_summary(await api(client, RAG, "/llm/settings"))
                    report["llm_settings_after"] = after
                    require(after == settings_before, "AI model/reasoning settings changed during the run")
                    report["checks"].append("global AI model, reasoning and settings version unchanged")
                except Exception as error:
                    report["settings_check_error"] = safe_error(error)
                    report["passed"] = False
            report["total_ms"] = round((time.monotonic() - started) * 1000)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stt-db", type=Path, default=data_directory("STT", ROOT / ".env", ROOT / ".runtime") / "stt.sqlite3")
    parser.add_argument("--rag-db", type=Path, default=data_directory("RAG", ROOT / ".env.rag", ROOT / ".rag-data") / "registry.sqlite")
    args = parser.parse_args()
    try:
        report = asyncio.run(run(args))
    except Exception as error:
        report = {"passed": False, "synthetic": True, "physical_microphone": False, "error": safe_error(error)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "passed": report["passed"],
        "synthetic": True,
        "physical_microphone": False,
        "first_stable_ms": report.get("first_stable_ms"),
        "first_result_ms": report.get("first_result_ms"),
        "first_popup_ms": report.get("first_popup_ms"),
        "jobs": report.get("job_counts"),
        "cleanup_confirmed": report.get("cleanup", {}).get("subscription_cleanup_confirmed", False),
        "error": report.get("error"),
        "report": str(OUTPUT.relative_to(ROOT)),
    }, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
