import asyncio
import importlib.metadata
import json
import logging
import platform
import subprocess
import time
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.modules.system.catalog import default_engine

from .audio import AudioDecodeError, close_mapped_audio, decode, save_wav
from .engines.base import ASRResult, Word
from .speaker_mapper import SpeakerMapper
from .transcript_assembler import assemble


class FileService:
    def __init__(self, settings, repo, workers):
        self.settings, self.repo, self.workers = settings, repo, workers
        self.active = None
        self.management_busy = False
        self.tasks = set()
        self.uploads = {}

    @lru_cache(maxsize=1)
    def environment(self):
        hardware = {}
        if platform.system() == "Darwin":
            for name, key in (("machdep.cpu.brand_string", "chip"), ("hw.memsize", "memory_bytes")):
                result = subprocess.run(
                    ["/usr/sbin/sysctl", "-n", name], capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    hardware[key] = result.stdout.strip()
        versions = {}
        for package in ("mlx-whisper", "faster-whisper", "mlx", "pyannote.audio", "silero-vad", "onnxruntime", "torch", "soxr"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = "not installed"
        return {
            "hardware": hardware,
            "packages": versions,
            "system": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "engine": self.settings.engine,
            "models": self.workers.manifest,
            "asr_device": "mock" if self.settings.engine == "fake" else (
                "CPU · int8" if (default_engine() if self.settings.asr_backend == "auto" else self.settings.asr_backend)
                == "faster-whisper" else "Apple Silicon MLX"
            ),
            "default_model": self.settings.default_model,
            "diarization_device": self.workers.health.get("diar", {}).get("models", {}).get("diarization", {}).get("device", "loading"),
        }

    def claim(self, sid):
        if self.active is not None or self.management_busy:
            raise RuntimeError("BUSY")
        self.active = sid

    def release(self, sid):
        if self.active == sid:
            self.active = None

    def launch(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        def finished(done):
            self.tasks.discard(done)
            error = None if done.cancelled() else done.exception()
            self.repo.record("stt.task_finished", state="CANCELLED" if done.cancelled() else "FAILED" if error else "COMPLETED",
                             error_type=type(error).__name__ if error else None)

        task.add_done_callback(finished)
        return task

    async def run(self, sid, jid, path: Path, upload=None, resume=None):
        session = self.repo.get(sid)
        if not session:
            if upload:
                await upload.close()
                upload.dispose()
                self.uploads.pop(sid, None)
            path.unlink(missing_ok=True)
            self.release(sid)
            return
        generation = session["generation"]
        total_start = time.perf_counter()
        timings = {}
        current_stage = "QUEUED"
        pcm_path = path.with_suffix(".f32")
        decoder = None
        checkpoint = pcm_path.with_suffix(".diar.json")

        def alive():
            return self.repo.valid(sid, generation)

        def stage(value):
            nonlocal current_stage
            current_stage = value
            if alive():
                self.repo.state(sid, value)
                self.repo.job(jid, sid, value)

        try:
            if resume is None:
                stage("PREPROCESSING")
                started = time.perf_counter()
                if upload:
                    decoder = asyncio.create_task(upload.decode(pcm_path, self.settings.max_file_seconds))
                    while not upload.probed:
                        if decoder.done():
                            await decoder
                        if not alive():
                            return
                        upload.check()
                        await asyncio.sleep(0.1)
                    diagnostics = upload.diagnostics
                else:
                    audio, diagnostics = await asyncio.to_thread(
                        decode, path, self.settings.max_file_seconds, pcm_path
                    )
                timings["preprocess_seconds"] = time.perf_counter() - started
                if not alive():
                    return
                session = self.repo.get(sid)
                options = session["options"]
                stage("TRANSCRIBING")
                words = []
                chunk_size = self.settings.file_chunk_seconds * 16000
                timings["asr_seconds"] = 0
                start = 0
                while True:
                    if not alive():
                        return
                    if upload:
                        upload.check()
                        if decoder.done():
                            await decoder
                        available = pcm_path.stat().st_size // 4 if pcm_path.exists() else 0
                        finished = decoder.done()
                    else:
                        available, finished = len(audio), True
                    if finished and start >= available:
                        break
                    window = min(chunk_size, (12 if start == 0 else 30) * 16000) if upload else chunk_size
                    stop = min(start + window, available)
                    if not finished and available < start + window + 2 * 16000:
                        await asyncio.sleep(0.1)
                        continue
                    # Context on both sides; each word belongs to the central window
                    # containing its midpoint, so overlap does not duplicate speech.
                    left, right = max(0, start - 2 * 16000), min(available, stop + 2 * 16000)
                    if upload:
                        mapped = np.memmap(
                            pcm_path, dtype="<f4", mode="r", offset=left * 4, shape=(right - left,)
                        )
                        try:
                            samples = np.array(mapped)
                        finally:
                            close_mapped_audio(mapped)
                    else:
                        samples = np.array(audio[left:right])
                    if not np.isfinite(samples).all():
                        raise AudioDecodeError("INVALID_DECODED_AUDIO")
                    chunk = await self.workers.run("asr", samples, options)
                    timings["asr_seconds"] += chunk.diagnostics["inference_seconds"]
                    if not alive():
                        return
                    words.extend(
                        Word(max(0, w.start + left / 16000), min(available / 16000, w.end + left / 16000), w.text)
                        for w in chunk.words
                        if start / 16000 <= (w.start + w.end) / 2 + left / 16000 < stop / 16000
                    )
                    self.repo.publish(
                        sid,
                        generation,
                        assemble(sid, "file", words, [], boundaries=self.repo.manual_boundaries(sid)),
                    )
                    duration = diagnostics.get("duration_seconds", available / 16000)
                    self.repo.state(
                        sid,
                        "TRANSCRIBING",
                        duration_seconds=duration,
                        transcribed_seconds=stop / 16000,
                        progress_percent=min(100, round(stop / 16000 / duration * 100, 1)),
                    )
                    start = stop
                if upload:
                    audio = np.memmap(pcm_path, dtype="<f4", mode="r")
                asr = ASRResult(words)
            else:
                audio = np.memmap(pcm_path, dtype="<f4", mode="r")
                diagnostics = resume["diagnostics"]
                timings = resume["timings"]
                asr = ASRResult([Word(**word) for word in resume["words"]])
                options = session["options"]
                total_start -= resume.get("elapsed_seconds", 0)
            checkpoint_tmp = checkpoint.with_suffix(".tmp")
            checkpoint_tmp.write_text(json.dumps({
                "generation": generation, "jid": jid,
                "words": [asdict(word) for word in asr.words],
                "diagnostics": diagnostics, "timings": timings,
                "elapsed_seconds": time.perf_counter() - total_start,
            }))
            checkpoint_tmp.replace(checkpoint)
            stage("DIARIZING")
            self.repo.state(sid, "DIARIZING", diar_stage=1, diar_total=0,
                            diar_completed=0, diar_stage_percent=0, diar_started_at=time.time())

            def progress(metrics):
                if alive() and self.repo.get(sid)["state"] == "DIARIZING":
                    self.repo.state(sid, "DIARIZING", **metrics)

            partial = False
            turns, overlaps = [], []
            try:
                diar = await self.workers.run("diar", audio, options, on_progress=progress)
                turns = SpeakerMapper().map(diar.turns)
                overlaps = diar.overlap_regions
                timings["diar_seconds"] = diar.diagnostics["inference_seconds"]
            except Exception as exc:
                partial = True
                self.repo.warning(sid, {"type": "diarization.failed", "code": type(exc).__name__})
            if not alive():
                return
            stage("MERGING")
            started = time.perf_counter()
            self.repo.publish(
                sid,
                generation,
                assemble(
                    sid,
                    "file",
                    asr.words,
                    turns,
                    overlaps,
                    final=True,
                    boundaries=self.repo.manual_boundaries(sid),
                ),
            )
            timings["merge_seconds"] = time.perf_counter() - started
            if options["retain_audio"]:
                dest = self.settings.data_dir / "audio" / f"{sid}.wav"
                await asyncio.to_thread(save_wav, dest, audio)
                if not alive():
                    dest.unlink(missing_ok=True)
                    return
                session = self.repo.get(sid)
                session["audio_retained"] = True
                self.repo.save(session)
            timings["total_seconds"] = time.perf_counter() - total_start
            timings["rtf"] = timings["total_seconds"] / diagnostics["duration_seconds"]
            state = "PARTIAL" if partial else "COMPLETED"
            self.repo.state(sid, state, **diagnostics, **timings)
            self.repo.job(jid, sid, state, metrics=timings)
        except Exception as exc:
            code = exc.code if isinstance(exc, AudioDecodeError) else type(exc).__name__
            details = exc.details if isinstance(exc, AudioDecodeError) else {}
            logging.getLogger(__name__).warning(
                "File processing failed: session=%s stage=%s code=%s details=%s",
                sid,
                current_stage,
                code,
                details,
            )
            if alive():
                self.repo.state(sid, "FAILED")
                self.repo.warning(
                    sid, {"type": "file.failed", "code": code, "stage": current_stage, **details}
                )
                self.repo.job(jid, sid, "FAILED", error=code, stage=current_stage, details=details)
        finally:
            if upload:
                await upload.close()
                if decoder and not decoder.done():
                    decoder.cancel()
                if decoder:
                    await asyncio.gather(decoder, return_exceptions=True)
                upload.dispose()
                self.uploads.pop(sid, None)
            # Windows does not unlink an open memory-mapped PCM file.
            close_mapped_audio(locals().get("audio"))
            path.unlink(missing_ok=True)
            pcm_path.unlink(missing_ok=True)
            checkpoint.unlink(missing_ok=True)
            if not alive():
                (self.settings.data_dir / "audio" / f"{sid}.wav").unlink(missing_ok=True)
            self.release(sid)

    def resume_pending(self):
        """Resume saved words at diarization after an interrupted service restart."""
        for checkpoint in sorted((self.settings.data_dir / "tmp").glob("session_*.diar.json")):
            sid = checkpoint.name.removesuffix(".diar.json")
            pcm = checkpoint.with_name(sid + ".f32")
            session = self.repo.get(sid)
            try:
                saved = json.loads(checkpoint.read_text())
                valid = (
                    session and session["state"] == "INTERRUPTED"
                    and session["mode"] == "file"
                    and session["generation"] == saved["generation"]
                    and pcm.is_file() and pcm.stat().st_size > 0
                    and pcm.stat().st_size % 4 == 0
                    and abs(pcm.stat().st_size / 64000 - saved["diagnostics"]["duration_seconds"]) < 0.01
                )
                if not valid:
                    raise ValueError("STALE_CHECKPOINT")
                [Word(**word) for word in saved["words"]]
                self.claim(sid)
            except (ValueError, KeyError, TypeError, OSError):
                checkpoint.unlink(missing_ok=True)
                pcm.unlink(missing_ok=True)
                continue
            session["warnings"] = [w for w in session["warnings"] if w["type"] != "service.restarted"]
            self.repo.save(session)
            self.repo.state(sid, "DIARIZING", diar_stage=1, diar_total=0,
                            diar_completed=0, diar_stage_percent=0, diar_started_at=time.time())
            self.launch(self.run(sid, saved["jid"], pcm.with_suffix(".input"), resume=saved))
            break
