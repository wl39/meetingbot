"""Portable regressions for Windows file I/O; no speech model downloads."""

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_api import wav

from app.modules.stt import workers
from app.modules.stt.audio import AudioDecodeError, close_mapped_audio, decode
from app.modules.stt.engines.base import DiarizationResult
from app.modules.stt.progress import write_progress
from app.modules.stt.routes.sessions import delete
from app.modules.stt.settings import Settings
from app.modules.stt.upload_stream import StreamingUpload


@pytest.mark.asyncio
async def test_upload_without_positional_io_preserves_binary_data(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "pread", raising=False)
    monkeypatch.delattr(os, "pwrite", raising=False)
    monkeypatch.setattr(StreamingUpload, "chunk_bytes", 4096)
    body = bytes(range(256)) * 48  # Includes CR, LF and DOS end-of-file byte 0x1a.
    upload = StreamingUpload(tmp_path / "한글 녹음.input", len(body))
    try:
        for index in (2, 0, 1):
            await upload.put(index, body[index * 4096 : (index + 1) * 4096])
        await upload.finish()
        offsets = [0, 4083, 8187, 32, 9000, 7777] * 8
        chunks = await asyncio.gather(*(asyncio.to_thread(upload.read_at, 64, offset) for offset in offsets))
        assert chunks == [body[offset : offset + 64] for offset in offsets]
        assert upload.path.read_bytes() == body
    finally:
        await upload.close()
        upload.dispose()
    assert not upload.path.exists()


def test_upload_descriptor_requests_windows_binary_mode(tmp_path, monkeypatch):
    real_open = os.open
    binary_flag = getattr(os, "O_BINARY", 0x40000000)
    windows_binary = hasattr(os, "O_BINARY")
    flags_seen = []

    def open_binary(path, flags, mode):
        flags_seen.append(flags)
        return real_open(path, flags if windows_binary else flags & ~binary_flag, mode)

    monkeypatch.setattr(os, "O_BINARY", binary_flag, raising=False)
    monkeypatch.setattr(os, "open", open_binary)
    upload = StreamingUpload(tmp_path / "binary.input", 128)
    try:
        assert flags_seen[0] & binary_flag
    finally:
        upload.dispose()


@pytest.mark.parametrize("invalid", ["too_long", "nan"])
def test_decode_failure_releases_mapping_before_cleanup(tmp_path, monkeypatch, invalid):
    samples = np.zeros(32000 if invalid == "too_long" else 16000, dtype="<f4")
    if invalid == "nan":
        samples[0] = np.nan
    mappings = []
    real_close = close_mapped_audio
    real_unlink = Path.unlink

    def close(audio):
        mappings.append(audio)
        real_close(audio)

    def unlink(path, *args, **kwargs):
        if path.suffix == ".f32" and any(not audio._mmap.closed for audio in mappings):
            raise PermissionError("Windows cannot unlink an open mapping")
        return real_unlink(path, *args, **kwargs)

    def run(args, **kwargs):
        if "-show_format" in args:
            info = {"format": {}, "streams": [{"codec_type": "audio", "channels": 1}]}
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(info).encode())
        kwargs["stdout"].write(samples.tobytes())
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr("app.modules.stt.audio.close_mapped_audio", close)
    monkeypatch.setattr(Path, "unlink", unlink)
    monkeypatch.setattr(subprocess, "run", run)
    pcm = tmp_path / "decoded.f32"
    with pytest.raises(AudioDecodeError) as error:
        decode(tmp_path / "recording.input", 1, pcm)
    assert error.value.code == ("AUDIO_TOO_LONG" if invalid == "too_long" else "INVALID_DECODED_AUDIO")
    assert len(mappings) == 1 and mappings[0]._mmap.closed
    assert not pcm.exists()


@pytest.mark.parametrize("fail", [False, True])
def test_worker_releases_mapping_even_when_engine_keeps_reference(tmp_path, monkeypatch, fail):
    path = tmp_path / "회의 원음.f32"
    np.zeros(16000, dtype="<f4").tofile(path)
    received = []

    def diarize(audio, options):
        received.append(audio)
        if fail:
            raise RuntimeError("inference failed")
        return DiarizationResult([])

    monkeypatch.setattr(workers, "_ENGINES", {
        "kind": "diar", "mode": "real", "diarization": SimpleNamespace(diarize=diarize),
    })
    if fail:
        with pytest.raises(RuntimeError, match="inference failed"):
            workers.infer({"pcm_path": str(path)}, {})
    else:
        workers.infer({"pcm_path": str(path)}, {})
    assert received[0]._mmap.closed
    path.unlink()  # Actual Windows CI verifies the operating system lock is gone.


@pytest.mark.asyncio
async def test_spawn_workers_process_unicode_pcm_path(tmp_path):
    settings = Settings(engine="fake", data_dir=tmp_path)
    settings.prepare()
    path = tmp_path / "tmp" / "한글 음성.f32"
    np.zeros(16000, dtype="<f4").tofile(path)
    audio = np.memmap(path, dtype="<f4", mode="r")
    worker = workers.Workers(settings)
    try:
        await worker.prepare()
        assert all(item["ready"] for item in worker.health.values())
        result = await worker.run("diar", audio, {"model": "small"})
        assert result.turns[0].end == 1
        close_mapped_audio(audio)
        path.unlink()
    finally:
        close_mapped_audio(audio)
        for pool in worker.pools.values():
            pool.shutdown(wait=True, cancel_futures=True)


def test_ffmpeg_handles_unicode_and_spaces_in_paths(tmp_path):
    source = tmp_path / "회의 녹음.wav"
    pcm = tmp_path / "변환 파일.f32"
    source.write_bytes(wav())
    audio, info = decode(source, 5, pcm)
    try:
        assert info["duration_seconds"] == 1
        assert len(audio) == 16000
    finally:
        close_mapped_audio(audio)
    pcm.unlink()


@pytest.mark.asyncio
async def test_delete_defers_files_owned_by_active_processing(tmp_path, monkeypatch):
    from app.modules.stt.routes import sessions

    sid = "session_active"
    paths = [tmp_path / "tmp" / f"{sid}.input", tmp_path / "audio" / f"{sid}.wav"]
    for path in paths:
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"still open")
    deleted = []
    service = SimpleNamespace(
        active=sid, uploads={}, settings=SimpleNamespace(data_dir=tmp_path),
        repo=SimpleNamespace(delete=deleted.append),
    )
    monkeypatch.setattr(sessions, "resources", lambda request: service)
    monkeypatch.setattr(sessions, "get_session", lambda service, sid: {})
    real_unlink = Path.unlink

    def locked_unlink(path, *args, **kwargs):
        if path in paths:
            raise PermissionError("Windows file is in use")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    assert (await delete(sid, None)).status_code == 204
    assert deleted == [sid]
    assert all(path.exists() for path in paths)


def test_progress_file_reader_cannot_fail_inference(tmp_path, monkeypatch):
    def locked_replace(*args):
        raise PermissionError("Windows progress file reader is open")

    monkeypatch.setattr(Path, "replace", locked_replace)
    write_progress(tmp_path / "progress.json", {"diar_stage": 2})


@pytest.mark.asyncio
async def test_dispose_waits_for_in_flight_upload_io(tmp_path, monkeypatch):
    monkeypatch.delattr(os, "pwrite", raising=False)
    real_write = os.write
    entered, release = threading.Event(), threading.Event()

    def slow_write(fd, body):
        entered.set()
        assert release.wait(3)
        return real_write(fd, body)

    upload = StreamingUpload(tmp_path / "closing.input", 128)
    monkeypatch.setattr(os, "write", slow_write)
    writing = asyncio.create_task(asyncio.to_thread(upload.write_at, b"x" * 128, 0))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        disposing = asyncio.create_task(asyncio.to_thread(upload.dispose))
        await asyncio.sleep(0.02)
        assert not disposing.done()
        release.set()
        await writing
        await disposing
        assert not upload.path.exists()
    finally:
        release.set()
        await writing
        upload.dispose()
