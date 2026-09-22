import asyncio
import time

import numpy as np

from .audio import PCMStream, save_wav
from .engines.base import Word
from .engines.silero_vad import SileroVAD
from .speaker_mapper import SpeakerMapper
from .transcript_assembler import assemble, merge_words


class LiveSession:
    def __init__(self, sid, start, service):
        self.sid, self.service = sid, service
        self.repo, self.workers, self.settings = service.repo, service.workers, service.settings
        session = self.repo.get(sid)
        self.generation, self.options = session["generation"], session["options"]
        self.stream = PCMStream(start.sample_rate, self.settings.max_live_seconds)
        self.stream_id = start.stream_id
        self.audio = np.empty(self.settings.max_live_seconds * 16000 + 16000, dtype=np.float32)
        self.size = 0
        self.words, self.turns, self.overlaps = [], [], []
        self.mapper = SpeakerMapper()
        self.stable_before = 0
        self.processed = 0
        self.diar_until = 0
        self.asr_task = self.diar_task = None
        self.asr_attempt = 0
        self.diar_attempt = 0
        self.last_asr_submit = 0
        self.closing = False
        self.diar_failed = False
        self.asr_failed = False
        self.started = time.monotonic()
        self.vad = None
        self.last_speech = 0

    async def initialize(self):
        self.vad = await asyncio.to_thread(SileroVAD, self.settings.engine == "fake")
        self.repo.state(self.sid, "RECORDING")
        self.scheduler = asyncio.create_task(self.schedule())

    def alive(self):
        return self.repo.valid(self.sid, self.generation)

    async def append(self, audio):
        if self.size + len(audio) > len(self.audio):
            raise ValueError("BUFFER_LIMIT")
        self.audio[self.size : self.size + len(audio)] = audio
        self.size += len(audio)
        self.last_speech = await asyncio.to_thread(self.vad.feed, audio)

    async def receive(self, data):
        audio, warning = self.stream.push(data)
        if warning:
            self.repo.warning(self.sid, dict(warning, stream_id=self.stream_id))
        await self.append(audio)
        return warning

    def publish(self, final=False):
        if not self.alive():
            return
        self.repo.publish(
            self.sid,
            self.generation,
            assemble(
                self.sid,
                "microphone",
                self.words,
                self.turns,
                self.overlaps,
                stable_ms=round(self.stable_before * 1000),
                final=final,
                boundaries=self.repo.manual_boundaries(self.sid),
            ),
        )

    def speech_window_start(self, end):
        begin = max(0, self.processed - 16000)
        relevant = [r for r in self.vad.speech_ranges if r[1] > begin and r[0] < end]
        return max(begin, relevant[0][0] - 4800) if relevant else None

    async def transcribe(self, end, final=False):
        begin = self.speech_window_start(end)
        if begin is None:
            # VAD-confirmed silence advances audio position without model inference or timestamp compaction.
            self.processed = end
            self.asr_attempt = end
            self.stable_before = end / 16000
            self.publish()
            return
        snapshot = self.audio[begin:end].copy()
        submitted = time.monotonic()
        try:
            result = await self.workers.run("asr", snapshot, self.options)
            if not self.alive():
                return
            incoming = [
                Word(w.start + begin / 16000, min(w.end + begin / 16000, end / 16000), w.text)
                for w in result.words
                if w.start < len(snapshot) / 16000
            ]
            self.words = merge_words(self.words, incoming, begin / 16000, end / 16000, self.stable_before)
            silence = end - self.last_speech >= 11200 and self.last_speech <= end
            self.stable_before = max(
                self.stable_before, end / 16000 if final or silence else max(0, end / 16000 - 1)
            )
            self.processed = end
            self.asr_failed = False
            self.publish()
            session = self.repo.get(self.sid)
            m = session["metrics"]
            m.update(
                processed_audio_ms=round(end / 16),
                audio_backlog_ms=round((self.size - end) / 16),
                asr_wall_seconds=time.monotonic() - submitted,
                asr_inference_seconds=result.diagnostics["inference_seconds"],
                retained_pcm_bytes=self.audio.nbytes,
                audio_input_ms=round(self.size / 16),
            )
            if self.words:
                m.setdefault("first_caption_seconds", time.monotonic() - self.started)
            if any(u["status"] == "stable" for u in session["utterances"]):
                m.setdefault("first_stable_seconds", time.monotonic() - self.started)
            self.repo.save(session)
        except Exception as exc:
            self.asr_failed = True
            self.repo.warning(self.sid, {"type": "asr.failed", "code": type(exc).__name__})
        finally:
            self.asr_attempt = end

    async def diarize(self, end):
        try:
            result = await self.workers.run("diar", self.audio[:end].copy(), self.options)
            if not self.alive() or end < self.diar_until:
                return
            self.turns = self.mapper.map(result.turns)
            self.overlaps = result.overlap_regions
            self.diar_until = end
            self.diar_failed = False
            self.publish()
            session = self.repo.get(self.sid)
            session["metrics"].update(
                diarization_until_ms=round(end / 16),
                diarization_lag_ms=round((self.size - end) / 16),
                diarization_seconds=result.diagnostics["inference_seconds"],
            )
            self.repo.save(session)
        except Exception as exc:
            self.diar_failed = True
            self.repo.warning(self.sid, {"type": "diarization.failed", "code": type(exc).__name__})
        finally:
            self.diar_attempt = end

    async def schedule(self):
        # At most one inference of each kind; pending snapshots are taken from the latest buffer.
        while not self.closing and self.alive():
            now = time.monotonic()
            idle_asr = self.asr_task is None or self.asr_task.done()
            has_speech = self.last_speech > self.asr_attempt
            has_tail = self.processed > 0 and self.stable_before < self.processed / 16000
            silence = self.size - self.last_speech >= 11200
            if idle_asr and (has_speech or (has_tail and silence)) and self.size > self.asr_attempt:
                if now - self.last_asr_submit >= self.settings.asr_interval:
                    # Catch up without skipping input when inference is slower than audio reception.
                    end = min(self.size, max(self.processed, 0) + 12 * 16000)
                    begin = self.speech_window_start(end)
                    # A first syllable can occupy Whisper's only worker for many
                    # seconds during decoding fallback. Wait for speech context,
                    # measured after cropping initial silence, before a partial run.
                    # An ended short phrase and explicit stop still drain immediately.
                    enough_context = begin is not None and (end - begin >= 2 * 16000 or silence)
                    if end > self.processed and begin is None:
                        # VAD-confirmed silence needs no worker or inference cadence.
                        # Otherwise a long pause advances only 12 seconds per ASR
                        # interval before reaching the speech already in the buffer.
                        await self.transcribe(end)
                    elif end > self.processed and enough_context:
                        self.asr_task = asyncio.create_task(self.transcribe(end))
                        self.last_asr_submit = now
            idle_diar = self.diar_task is None or self.diar_task.done()
            if idle_diar and self.size - self.diar_attempt >= self.settings.diar_interval * 16000:
                self.diar_task = asyncio.create_task(self.diarize(self.size))
            await asyncio.sleep(0.1)

    async def finish(self, interrupted=False):
        self.closing = True
        try:
            await self.scheduler
            if not self.alive():
                return
            self.repo.state(self.sid, "FINALIZING")
            await self.append(self.stream.flush())
            for task in (self.asr_task, self.diar_task):
                if task:
                    await task
            # Drain every remaining window, including the final short utterance.
            while self.processed < self.size and self.alive():
                end = min(self.size, self.processed + 12 * 16000)
                if self.last_speech == 0 and not self.words:
                    self.processed = self.size
                    break
                previous = self.processed
                await self.transcribe(end, final=end == self.size)
                if self.processed == previous:
                    break
            if self.alive() and self.size:
                await self.diarize(self.size)
            if not self.alive():
                return
            self.stable_before = self.size / 16000
            self.publish(final=True)
            if self.options["retain_audio"] and self.size:
                path = self.settings.data_dir / "audio" / f"{self.sid}.wav"
                await asyncio.to_thread(save_wav, path, self.audio[: self.size])
                if not self.alive():
                    path.unlink(missing_ok=True)
                    return
                session = self.repo.get(self.sid)
                session["audio_retained"] = True
                self.repo.save(session)
            state = (
                "INTERRUPTED"
                if interrupted
                else ("PARTIAL" if self.diar_failed or self.asr_failed else "COMPLETED")
            )
            self.repo.state(
                self.sid,
                state,
                audio_input_ms=round(self.size / 16),
                total_seconds=time.monotonic() - self.started,
            )
        except Exception as exc:
            if self.alive():
                self.repo.warning(self.sid, {"type": "finalization.failed", "code": type(exc).__name__})
                self.repo.state(self.sid, "PARTIAL")
        finally:
            # Even deleted sessions retain the concurrency lock until non-preemptible work ends.
            await asyncio.gather(*(t for t in (self.asr_task, self.diar_task) if t), return_exceptions=True)
            self.audio = np.empty(0, dtype=np.float32)
            self.vad = None
            if not self.alive():
                (self.settings.data_dir / "audio" / f"{self.sid}.wav").unlink(missing_ok=True)
            self.service.release(self.sid)
