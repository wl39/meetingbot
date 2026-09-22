"""Multipart and incremental audio upload endpoints."""

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError

from app.access import prepare_options, register_session
from app.contracts.utterance import uid

from ..schemas import FileUploadStart, Options
from ..upload_stream import StreamingUpload
from .dependencies import check_ready, resources

router = APIRouter()


@router.post("/files", status_code=202)
async def upload(request: Request, file: UploadFile = File(...), options: str = Form("{}")):
    service = resources(request)
    try:
        config = Options.model_validate_json(options)
    except ValidationError as exc:
        raise HTTPException(422, "INVALID_OPTIONS") from exc
    check_ready(service, config)
    if Path(file.filename or "").suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
        raise HTTPException(415, "UNSUPPORTED_AUDIO_FORMAT")
    prepare_options(request, config)
    session = register_session(request, service.repo.create("file", config.model_dump(), service.environment()))
    sid, jid = session["id"], uid("job")
    service.claim(sid)
    path = service.settings.data_dir / "tmp" / f"{sid}.input"
    try:
        size = 0
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > service.settings.max_file_bytes:
                    raise HTTPException(413, "FILE_TOO_LARGE")
                target.write(chunk)
        if not size:
            raise HTTPException(422, "EMPTY_FILE")
        service.repo.job(jid, sid, "QUEUED")
        service.launch(service.run(sid, jid, path))
        return {"session_id": sid, "job_id": jid}
    except BaseException:
        path.unlink(missing_ok=True)
        service.repo.delete(sid)
        service.release(sid)
        raise
    finally:
        await file.close()


@router.post("/files/stream", status_code=201)
async def start_upload(config: FileUploadStart, request: Request):
    s = resources(request)
    check_ready(s, config.options)
    if Path(config.filename).suffix.lower() not in {".wav", ".mp3", ".m4a", ".flac"}:
        raise HTTPException(415, "UNSUPPORTED_AUDIO_FORMAT")
    if config.size > s.settings.max_file_bytes:
        raise HTTPException(413, "FILE_TOO_LARGE")
    prepare_options(request, config.options)
    session = register_session(request, s.repo.create("file", config.options.model_dump(), s.environment()))
    sid, jid = session["id"], uid("job")
    s.claim(sid)
    try:
        upload = StreamingUpload(s.settings.data_dir / "tmp" / f"{sid}.input", config.size)
        s.uploads[sid] = upload
        session["source_file"] = {"name": config.filename, "size": config.size}
        s.repo.save(session)
        s.repo.state(sid, "UPLOADING", upload_percent=0)
        s.repo.job(jid, sid, "UPLOADING")
        s.launch(s.run(sid, jid, upload.path, upload))
    except BaseException:
        s.repo.delete(sid)
        s.release(sid)
        raise
    return {"session_id": sid, "job_id": jid, "chunk_bytes": upload.chunk_bytes}


@router.put("/files/{sid}/chunks/{index}")
async def upload_chunk(sid: str, index: int, request: Request):
    s = resources(request)
    upload = s.uploads.get(sid)
    if upload is None or not s.repo.get(sid):
        raise HTTPException(404, "UPLOAD_NOT_FOUND")
    body = bytearray()
    async for part in request.stream():
        body.extend(part)
        if len(body) > upload.chunk_bytes:
            raise HTTPException(413, "UPLOAD_CHUNK_TOO_LARGE")
    try:
        await upload.put(index, bytes(body))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    session = s.repo.get(sid)
    if session:
        size = sum(min(upload.chunk_bytes, upload.size - i * upload.chunk_bytes) for i in upload.received)
        s.repo.state(sid, session["state"], upload_percent=round(size / upload.size * 100, 1))
    return {"received_chunks": len(upload.received)}


@router.post("/files/{sid}/finish", status_code=202)
async def finish_upload(sid: str, request: Request):
    s = resources(request)
    upload = s.uploads.get(sid)
    if upload is None or not s.repo.get(sid):
        raise HTTPException(404, "UPLOAD_NOT_FOUND")
    try:
        await upload.finish()
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"session_id": sid}
