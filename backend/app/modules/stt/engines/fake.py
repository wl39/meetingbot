import numpy as np

from .base import ASRResult, DiarizationResult, Turn, Word


class FakeASR:
    def transcribe(self, audio, options):
        if not len(audio) or np.max(np.abs(audio)) < 0.001:
            return ASRResult([])
        duration = len(audio) / 16000
        texts = [" 모의", " 전사", " 결과입니다."]
        return ASRResult(
            [Word(i * duration / 3, (i + 1) * duration / 3, t) for i, t in enumerate(texts)],
            diagnostics={"fake": True},
        )


class FakeDiarizer:
    def diarize(self, audio, options):
        return DiarizationResult([Turn(0, len(audio) / 16000, "SPEAKER_00")], diagnostics={"fake": True})
