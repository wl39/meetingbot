import json
import subprocess

import numpy as np
import pytest

from app.modules.stt.audio import AudioDecodeError, decode
from app.modules.stt.engines.pyannote_engine import bounded_training_set


@pytest.mark.parametrize("duration", [None, "N/A", "0", "nan"])
def test_missing_duration_uses_bounded_decoded_audio(monkeypatch, tmp_path, duration):
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if "-show_format" in args:
            info = {"format": {"duration": duration}, "streams": [{"codec_type": "audio", "channels": 1}]}
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(info).encode())
        return subprocess.CompletedProcess(args, 0, stdout=np.zeros(16000, dtype="<f4").tobytes())

    monkeypatch.setattr(subprocess, "run", run)
    audio, info = decode(tmp_path / "recording.input", 600)
    assert len(audio) == 16000 and info["duration_seconds"] == 1
    assert calls[1][calls[1].index("-t") + 1] == "601"


def test_unknown_duration_cannot_bypass_limit(monkeypatch, tmp_path):
    def run(args, **kwargs):
        if "-show_format" in args:
            info = {"format": {}, "streams": [{"codec_type": "audio", "channels": 1}]}
            output = json.dumps(info).encode()
        else:
            output = np.zeros(32000, dtype="<f4").tobytes()
        return subprocess.CompletedProcess(args, 0, stdout=output)

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(AudioDecodeError) as error:
        decode(tmp_path / "recording.input", 1)
    assert error.value.code == "AUDIO_TOO_LONG"


def test_speaker_training_bound_spans_entire_recording():
    count = 12000
    indices = np.arange(count)
    embeddings = np.column_stack((indices, indices))
    sampled, chunks, speakers = bounded_training_set(embeddings, indices, indices % 3)
    assert len(sampled) == 4096
    assert chunks[0] == 0 and chunks[-1] == count - 1
    assert np.all(sampled[:, 0] == chunks)
    assert np.all(speakers == chunks % 3)
    assert np.all(np.diff(chunks) > 0)


def test_worker_maps_pcm_file(tmp_path):
    from app.modules.stt import workers

    path = tmp_path / "audio.f32"
    np.zeros(16000, dtype="<f4").tofile(path)
    workers.initialize("diar", "fake", {})
    workers.prepare()
    try:
        result = workers.infer({"pcm_path": str(path)}, {"model": "large-v3-turbo"})
        assert result.turns[0].end == 1
    finally:
        workers._ENGINES.clear()
