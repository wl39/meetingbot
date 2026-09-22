"""Streaming speech context, short utterance drainage and ASR backpressure."""

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from app.modules.stt.engines.fake import FakeASR, FakeDiarizer
from app.modules.stt.live_service import LiveSession
from app.modules.stt.repository import Repository
from app.modules.stt.schemas import Options, StartFrame
from app.modules.stt.settings import Settings


class RecordingWorkers:
    def __init__(self):
        self.windows = []
        self.asr_started = asyncio.Event()

    async def run(self, kind, audio, options):
        if kind == "asr":
            self.windows.append(len(audio) / 16000)
            self.asr_started.set()
            result = FakeASR().transcribe(audio, options)
        else:
            result = FakeDiarizer().diarize(audio, options)
        result.diagnostics["inference_seconds"] = 0.001
        return result


async def live_session(tmp_path):
    repo = Repository(tmp_path / "stt.sqlite3")
    session = repo.create("microphone", Options().model_dump(), {})
    workers = RecordingWorkers()
    service = SimpleNamespace(repo=repo, workers=workers, release=lambda _: None,
                              settings=Settings(engine="fake", data_dir=tmp_path, max_live_seconds=130,
                                                asr_interval=2, diar_interval=180))
    live = LiveSession(session["id"], StartFrame(type="start", stream_id="test", sample_rate=16000), service)
    await live.initialize()
    return live, workers, repo


def audio(seconds, speech=True):
    return np.full(round(seconds * 16000), 0.2 if speech else 0, dtype=np.float32)


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_silence", [0, 20, 100])
async def test_first_syllable_waits_for_context_after_cropping_initial_silence(tmp_path, initial_silence):
    live, workers, repo = await live_session(tmp_path)
    try:
        if initial_silence:
            await live.append(audio(initial_silence, speech=False))
        await live.append(audio(0.2))
        # Let the real scheduler run twice: receiving a tiny onset must not occupy
        # the worker, even when the untrimmed capture already contains 20 seconds.
        await asyncio.sleep(0.22)
        assert workers.windows == []
        assert live.last_asr_submit == 0
        await live.append(audio(2))
        await asyncio.wait_for(workers.asr_started.wait(), timeout=1)
        assert len(workers.windows) == 1
        assert 2 <= workers.windows[0] < 3
        assert repo.get(live.sid)["utterances"][0]["start_ms"] >= max(0, initial_silence * 1000 - 300)
    finally:
        await live.finish()
        repo.db.close()


@pytest.mark.asyncio
async def test_short_phrase_is_transcribed_when_silence_marks_its_end(tmp_path):
    live, workers, repo = await live_session(tmp_path)
    try:
        await live.append(audio(0.3))
        await asyncio.sleep(0.12)
        assert workers.windows == []
        await live.append(audio(0.9, speech=False))
        await asyncio.wait_for(workers.asr_started.wait(), timeout=1)
        assert workers.windows == [1.2]
        assert any(u["status"] == "stable" for u in repo.get(live.sid)["utterances"])
    finally:
        await live.finish()
        repo.db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_stop_and_disconnect_drain_short_unsubmitted_speech(tmp_path, interrupted):
    live, workers, repo = await live_session(tmp_path)
    try:
        await live.append(audio(0.2))
        await asyncio.sleep(0.12)
        assert workers.windows == []
        await live.finish(interrupted=interrupted)
        result = repo.get(live.sid)
        assert workers.windows == [0.2]
        assert result["state"] == ("INTERRUPTED" if interrupted else "COMPLETED")
        assert result["metrics"]["audio_input_ms"] == 200
        assert result["utterances"] and all(u["status"] == "stable" for u in result["utterances"])
    finally:
        repo.db.close()


@pytest.mark.asyncio
async def test_stop_after_long_initial_silence_preserves_audio_timestamps(tmp_path):
    live, workers, repo = await live_session(tmp_path)
    try:
        await live.append(audio(100, speech=False))
        await live.append(audio(0.2))
        await live.finish()
        result = repo.get(live.sid)
        assert len(workers.windows) == 1 and workers.windows[0] < 1
        assert result["state"] == "COMPLETED"
        assert result["metrics"]["audio_input_ms"] == 100200
        assert result["utterances"][0]["start_ms"] >= 99700
        assert result["utterances"][-1]["end_ms"] == 100200
        assert all(u["status"] == "stable" for u in result["utterances"])
    finally:
        repo.db.close()
