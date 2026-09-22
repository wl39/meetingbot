"""Synthetic audio -> deployed real STT WebSocket -> bridge -> LLM/RAG -> red popup.

Never opens a hardware microphone or changes existing sessions, workspaces, or AI settings.
Run after services are ready: backend/.venv/bin/python scripts/meeting_stream_smoke.py
"""

import asyncio
import json
import re
import shutil
import struct
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
import websockets
from meeting_smoke import documents

ROOT = Path(__file__).resolve().parents[1]
STT = "http://127.0.0.1:8765/api/stt"
RAG = "http://127.0.0.1:8766/api/rag"
PHRASE = "운영 서버 로그 기록은 사십오 일 동안 서버에 남아요."
FIELDS = (
    "utterance_id",
    "revision",
    "text",
    "status",
    "speaker_id",
    "start_ms",
    "end_ms",
)


async def api(client, base, path, body=None, method=None):
    options = (
        {"content": body, "headers": {"Content-Type": "application/octet-stream"}}
        if isinstance(body, bytes)
        else ({"json": body} if body is not None else {})
    )
    response = await client.request(
        method or ("POST" if body is not None else "GET"), base + path, **options
    )
    response.raise_for_status()
    return response.json() if response.content else None


def synthesize(directory):
    """Use macOS speech synthesis to a file; playback and microphone APIs are unused."""
    source = directory / "meeting-synthetic.aiff"
    subprocess.run(
        ["/usr/bin/say", "-v", "Yuna", "-r", "145", "-o", str(source), PHRASE],
        check=True,
        timeout=30,
        capture_output=True,
    )
    ffmpeg = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    converted = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(source),
            "-t",
            "20",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        check=True,
        timeout=30,
        capture_output=True,
    )
    voice = np.frombuffer(converted.stdout, dtype="<f4").copy()
    assert 16000 < len(voice) < 20 * 16000 and np.isfinite(voice).all(), (
        "Invalid synthetic audio"
    )
    return np.concatenate(
        (np.zeros(8000, dtype="<f4"), voice, np.zeros(19200, dtype="<f4"))
    )


async def stream_audio(token, sid, audio, timings=None):
    snapshots = []
    started = time.monotonic()
    timings = timings if timings is not None else {}

    def mark(name):
        timings.setdefault(name, round((time.monotonic() - started) * 1000))
    async with websockets.connect(
        f"ws://127.0.0.1:8765/api/stt/sessions/{sid}/stream",
        origin="http://127.0.0.1:8765",
        subprotocols=["stt", "stt." + token],
        open_timeout=10,
        close_timeout=5,
    ) as websocket:
        await websocket.send(
            json.dumps(
                {
                    "type": "start",
                    "stream_id": "synthetic-meeting-" + uuid.uuid4().hex[:8],
                    "sample_rate": 16000,
                }
            )
        )
        async with asyncio.timeout(15):
            while True:
                message = json.loads(await websocket.recv())
                if message["type"] == "error":
                    raise RuntimeError(
                        "STT stream start failed: " + message.get("code", "UNKNOWN")
                    )
                if message["type"] == "ack" and message.get("action") == "start":
                    mark("start_ack_ms")
                    break

        async def send():
            sequence = -1
            for sequence, start in enumerate(range(0, len(audio), 1600)):
                chunk = audio[start : start + 1600]
                await websocket.send(
                    struct.pack("<IQI", sequence, start, len(chunk)) + chunk.tobytes()
                )
                mark("first_frame_sent_ms")
                await asyncio.sleep(len(chunk) / 16000)
            mark("audio_finished_sending_ms")
            await websocket.send(
                json.dumps({"type": "stop", "last_sequence": sequence})
            )
            mark("stop_sent_ms")

        sender = asyncio.create_task(send())
        try:
            async with asyncio.timeout(90):
                while True:
                    message = json.loads(await websocket.recv())
                    if message["type"] == "snapshot" and message.get("session"):
                        snapshots.append(message["session"])
                        utterances = message["session"].get("utterances", [])
                        if utterances:
                            mark("first_caption_snapshot_ms")
                        if any(u["status"] in {"stable", "corrected", "final"} for u in utterances):
                            mark("first_stable_snapshot_ms")
                    if message["type"] == "ack" and message.get("action") == "stop":
                        mark("stop_ack_ms")
                    if message["type"] in {"error", "deleted"}:
                        raise RuntimeError(
                            "STT stream failed: " + message.get("code", message["type"])
                        )
                    if message["type"] == "completed":
                        mark("completed_ms")
                        break
            await sender
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
    return snapshots, round((time.monotonic() - started) * 1000)


async def main():
    token = (ROOT / ".runtime/local-token").read_text().strip()
    report = {
        "synthetic": True,
        "fixture": "macOS Yuna Korean synthetic voice streamed as paced 16 kHz mono PCM; no hardware microphone",
        "scope": "Single synthetic speaker integration check, not a real meeting or recognition-accuracy benchmark",
        "pipeline": [
            "real STT WebSocket",
            "STT meeting bridge",
            "LLM extraction",
            "real E5 RAG",
            "LLM popup",
        ],
        "spoken_text": PHRASE,
        "checks": [],
        "cleanup": [],
        "passed": False,
    }
    sid = wid = upload_id = None
    started = time.monotonic()
    temporary = tempfile.TemporaryDirectory(prefix="meeting-stream-synthetic-")
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + token},
        timeout=55,
        trust_env=False,
        follow_redirects=False,
    ) as client:
        try:
            async with asyncio.timeout(300):
                health = await api(client, STT, "/health")
                assert health["active_session"] is None, (
                    "Existing active STT session; smoke did not start"
                )
                assert health["engine"] == "real", "Deployed STT must use real models"
                deadline = time.monotonic() + 75
                while not all(
                    health["workers"].get(k, {}).get("ready") for k in ("asr", "vad")
                ):
                    assert time.monotonic() < deadline, (
                        "STT workers did not become ready"
                    )
                    await asyncio.sleep(0.5)
                    health = await api(client, STT, "/health")
                    assert health["active_session"] is None, (
                        "Another STT session started"
                    )
                diagnostic = await api(client, STT, "/meeting/diagnostics")
                assert diagnostic["model"]["state"] == "READY", (
                    "Real RAG embedding model must be ready"
                )
                assert (
                    diagnostic["llm"]["global_allowed"]
                    and diagnostic["llm"]["configured"]
                ), "Existing AI configuration must already be enabled"
                report["llm_model"] = diagnostic["llm"]["model"]
                report["checks"].append(
                    "no existing active STT session; global AI settings read only"
                )
                upload = await api(
                    client,
                    RAG,
                    "/uploads",
                    {
                        "name": "음성 연동 임시 합성 검증 " + uuid.uuid4().hex[:6],
                        "folder_name": "meeting-stream-synthetic",
                        "description": "자동 검증 후 삭제하는 합성 정책 자료",
                        "files": [
                            {"path": name, "size": len(content.encode())}
                            for name, content in documents.items()
                        ],
                    },
                )
                upload_id = upload["id"]
                for file in upload["files"]:
                    await api(
                        client,
                        RAG,
                        f"/uploads/{upload_id}/files/{file['id']}",
                        documents[file["path"]].encode(),
                        "PUT",
                    )
                committed = await api(client, RAG, f"/uploads/{upload_id}/commit", {})
                wid, job_id = committed["workspace"]["id"], committed["job"]["job_id"]
                deadline = time.monotonic() + 90
                while True:
                    job = await api(
                        client, RAG, f"/workspaces/{wid}/index-jobs/{job_id}"
                    )
                    if job["state"] not in {"QUEUED", "RUNNING"}:
                        break
                    assert time.monotonic() < deadline, (
                        "Synthetic document index timeout"
                    )
                    await asyncio.sleep(0.5)
                assert job["state"] == "READY", "Synthetic document index failed"
                await api(
                    client,
                    RAG,
                    f"/workspaces/{wid}",
                    {
                        "external_llm_approved": True,
                        "provider_id": diagnostic["llm"]["provider_id"],
                    },
                    "PATCH",
                )
                report["checks"].append(
                    "temporary synthetic documents indexed; consent granted only to own workspace"
                )
                audio = await asyncio.to_thread(synthesize, Path(temporary.name))
                report["audio_seconds"] = round(len(audio) / 16000, 3)
                health = await api(client, STT, "/health")
                assert health["active_session"] is None, (
                    "Another STT session started; refusing to interfere"
                )
                available = health["workers"]["asr"].get("models", {})
                selected = (
                    "large-v3-turbo"
                    if available.get("large-v3-turbo", {}).get("ready")
                    else "small"
                )
                session = await api(
                    client,
                    STT,
                    "/sessions",
                    {
                        "model": selected,
                        "language": "ko",
                        "num_speakers": 1,
                        "retain_audio": False,
                    },
                )
                sid = session["id"]
                report["stt_model"] = selected
                snapshots, stream_ms = await stream_audio(token, sid, audio)
                session = await api(client, STT, f"/sessions/{sid}")
                report.update(
                    stt_state=session["state"],
                    stt_metrics=session["metrics"],
                    stt_warnings=session["warnings"],
                    stt_recognized_text=" ".join(
                        u["text"] for u in session["utterances"]
                    ),
                    had_partial_caption=any(
                        any(u["status"] == "partial" for u in s["utterances"])
                        for s in snapshots
                    ),
                    snapshot_count=len(snapshots),
                )
                stable = [
                    u
                    for u in session["utterances"]
                    if u["status"] in {"stable", "corrected"}
                ]
                candidates = [
                    u
                    for u in stable
                    if "로그" in u["text"] and re.search(r"45|사십\s*오", u["text"])
                ]
                assert candidates, (
                    "Real STT did not produce a stable log-retention claim containing 45 days"
                )
                utterance = max(candidates, key=lambda u: len(u["text"]))
                assert "운영" in utterance["text"], (
                    "Recognized claim lacks explicit production scope"
                )
                report["analyzed_utterance"] = {key: utterance[key] for key in FIELDS}
                analyze_started = time.monotonic()
                response = await api(
                    client,
                    STT,
                    f"/meeting/workspaces/{wid}/analyze",
                    {
                        "session_id": sid,
                        "utterance": report["analyzed_utterance"],
                        "context": [],
                        "revision_id": job["revision_id"],
                    },
                )
                report.update(
                    status=response["status"],
                    reason=response.get("reason"),
                    analysis=response.get("analysis"),
                    popup=response.get("popup"),
                    timings_ms={
                        "stt_stream": stream_ms,
                        "bridge_analyze": round(
                            (time.monotonic() - analyze_started) * 1000
                        ),
                        "rag_pipeline": response["timings_ms"],
                    },
                )
                popup = response.get("popup")
                assert response["status"] == "popup" and popup, (
                    "Meeting bridge did not return a popup"
                )
                assert popup["kind"] == "warning" and popup["color"] == "red", (
                    "Expected red correction"
                )
                assert re.search(r"90\s*일", popup["message"]), (
                    "Correction omitted 90-day policy"
                )
                sources = {e["evidence_id"]: e for e in response["evidence"]}
                assert (
                    popup["citations"] and set(popup["citations"]) <= sources.keys()
                ), "Invalid citation"
                assert all(e["workspace_id"] == wid for e in sources.values()), (
                    "Unexpected workspace evidence"
                )
                report["cited_source_text"] = [
                    sources[eid]["text"] for eid in popup["citations"]
                ]
                assert any("90일" in text for text in report["cited_source_text"]), (
                    "Missing 90-day source"
                )
                report["checks"].append(
                    "canonical real STT utterance passed through bridge to red popup with 90-day citation"
                )
                report["passed"] = True
        except Exception as error:
            # Exceptions contain only local endpoints or this synthetic fixture; credentials are never logged.
            report["error_type"] = type(error).__name__
            report["error"] = (
                str(error)
                if isinstance(error, AssertionError)
                else "Synthetic integration run failed"
            )
            raise
        finally:
            for base, path, label in (
                (
                    STT,
                    f"/sessions/{sid}" if sid else None,
                    "own synthetic STT session deleted",
                ),
                (
                    RAG,
                    f"/workspaces/{wid}"
                    if wid
                    else (f"/uploads/{upload_id}" if upload_id else None),
                    "own synthetic workspace/upload deleted",
                ),
            ):
                if path:
                    try:
                        await asyncio.wait_for(
                            api(client, base, path, method="DELETE"), timeout=20
                        )
                        report["cleanup"].append(label)
                    except (
                        httpx.HTTPError,
                        TimeoutError,
                        OSError,
                        ValueError,
                    ) as error:
                        report["passed"] = False
                        report["cleanup"].append(
                            "cleanup failed: " + type(error).__name__
                        )
            temporary.cleanup()
            report["cleanup"].append("temporary synthesized audio files deleted")
            report["total_ms"] = round((time.monotonic() - started) * 1000)
            (ROOT / "docs/meeting-stream-results.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            )
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    assert report["passed"], "Synthetic stream integration or cleanup did not pass"


if __name__ == "__main__":
    asyncio.run(main())
