"""Transcription sessions, corrections, retained audio, and exports."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.access import prepare_options, register_session
from app.contracts.utterance import uid
from app.modules.system.catalog import default_engine

from ..export import export, preview
from ..repository import Conflict
from ..schemas import Correction, Options, SpeakerPatch
from .dependencies import check_ready, get_session, resources

router = APIRouter()


@router.get("/health")
async def health(request: Request):
    s = resources(request)
    visitor = not request.state.principal.manages_data
    return {
        "engine": s.settings.engine,
        "asr_backend": default_engine() if s.settings.asr_backend == "auto" else s.settings.asr_backend,
        "default_model": s.settings.default_model,
        "management_busy": s.management_busy,
        "workers": s.workers.health,
        "active_session": (
            s.active if s.active and request.app.state.access.owner(s.active) == request.state.principal.subject
            else "busy" if s.active else None
        ),
        "environment": {} if visitor else {**s.environment(), "diarization_device": s.workers.health.get("diar", {}).get("models", {}).get("diarization", {}).get("device", "loading")},
        "limits": {
            "file_mb": s.settings.max_file_bytes // (1024 * 1024),
            "file_seconds": s.settings.max_file_seconds,
            "live_seconds": s.settings.max_live_seconds,
        },
        "audio_retention_default": False,
    }


@router.get("/sessions")
async def sessions(request: Request):
    return [
        {k: s[k] for k in ("id", "mode", "state", "created_at", "audio_retained")}
        for s in resources(request).repo.list()
        if request.app.state.access.owner(s["id"]) == request.state.principal.subject
    ]


@router.get("/jobs/{jid}")
async def job(jid: str, request: Request):
    result = resources(request).repo.get_job(jid)
    if not result:
        raise HTTPException(404, "JOB_NOT_FOUND")
    return result


@router.post("/sessions", status_code=201)
async def create_session(options: Options, request: Request):
    s = resources(request)
    check_ready(s, options, live=True)
    prepare_options(request, options)
    # Creation alone does not reserve the microphone; WS start atomically claims the slot.
    return register_session(request, s.repo.create("microphone", options.model_dump(), s.environment()))


@router.get("/sessions/{sid}")
async def snapshot(sid: str, request: Request):
    return get_session(resources(request), sid)


@router.patch("/sessions/{sid}/utterances/{utterance_id}")
async def correction(sid: str, utterance_id: str, patch: Correction, request: Request):
    s = resources(request)
    get_session(s, sid)
    try:
        return s.repo.correct(sid, utterance_id, patch)
    except Conflict as exc:
        raise HTTPException(409, "REVISION_CONFLICT") from exc
    except KeyError as exc:
        raise HTTPException(404, "UTTERANCE_NOT_FOUND") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/sessions/{sid}/speakers", status_code=201)
async def add_speaker(sid: str, patch: SpeakerPatch, request: Request):
    s = resources(request)
    session = get_session(s, sid)
    speaker_id = uid("spk_manual")
    session["speakers"][speaker_id] = patch.name
    s.repo.save(session)
    return {"speaker_id": speaker_id, "name": patch.name}


@router.patch("/sessions/{sid}/speakers/{speaker_id}")
async def rename_speaker(sid: str, speaker_id: str, patch: SpeakerPatch, request: Request):
    s = resources(request)
    session = get_session(s, sid)
    if speaker_id not in session["speakers"]:
        raise HTTPException(404, "SPEAKER_NOT_FOUND")
    session["speakers"][speaker_id] = patch.name
    s.repo.save(session)
    return session["speakers"]


@router.get("/sessions/{sid}/events")
async def events(sid: str, request: Request):
    s = resources(request)
    get_session(s, sid)
    return s.repo.events(sid)


@router.get("/sessions/{sid}/export")
async def download(
    sid: str,
    request: Request,
    format: Literal["txt", "srt", "json"] = "txt",
    view: Literal["utterance", "script"] = "utterance",
):
    s = resources(request)
    session = get_session(s, sid)
    data, content_type = export(session, format, s.repo.events(sid), view)
    return Response(
        data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{sid}.{format}"'},
    )


@router.get("/sessions/{sid}/export/preview")
async def export_preview(
    sid: str,
    request: Request,
    format: Literal["txt", "srt", "json"] = "txt",
    view: Literal["utterance", "script"] = "utterance",
):
    session = get_session(resources(request), sid)
    return preview(session, format, view)


@router.get("/sessions/{sid}/audio")
async def audio(sid: str, request: Request):
    s = resources(request)
    session = get_session(s, sid)
    path = s.settings.data_dir / "audio" / f"{sid}.wav"
    if not session["audio_retained"] or not path.is_file():
        raise HTTPException(404, "AUDIO_NOT_RETAINED")
    return FileResponse(path, media_type="audio/wav")


@router.post("/sessions/{sid}/reprocess", status_code=202)
async def reprocess(sid: str, request: Request):
    import shutil

    s = resources(request)
    original = get_session(s, sid)
    config = Options(**original["options"])
    check_ready(s, config)
    prepare_options(request, config)
    src = s.settings.data_dir / "audio" / f"{sid}.wav"
    if not original["audio_retained"] or not src.exists():
        raise HTTPException(409, "AUDIO_NOT_RETAINED")
    session = register_session(request, s.repo.create("file", config.model_dump(), s.environment()))
    new_sid, jid = session["id"], uid("job")
    s.claim(new_sid)
    dest = s.settings.data_dir / "tmp" / f"{new_sid}.input"
    try:
        shutil.copyfile(src, dest)
        s.repo.job(jid, new_sid, "QUEUED")
        s.launch(s.run(new_sid, jid, dest))
    except BaseException:
        dest.unlink(missing_ok=True)
        s.repo.delete(new_sid)
        s.release(new_sid)
        raise
    return {"session_id": new_sid, "job_id": jid}


@router.delete("/sessions/{sid}", status_code=204)
async def delete(sid: str, request: Request):
    s = resources(request)
    get_session(s, sid)
    # Deletion is a tombstone by absence: all worker writes require the original generation to exist.
    s.repo.delete(sid)
    if sid in s.uploads:
        await s.uploads[sid].close()
    # Active processing may still hold FFmpeg or WAV handles on Windows.
    # The processing task removes its files after those handles are closed.
    if s.active != sid:
        for directory, suffix in (("tmp", ".input"), ("audio", ".wav")):
            (s.settings.data_dir / directory / f"{sid}{suffix}").unlink(missing_ok=True)
    return Response(status_code=204)
