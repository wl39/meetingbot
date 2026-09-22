from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class ASRResult:
    words: list[Word]
    language: str = "ko"
    diagnostics: dict = field(default_factory=dict)


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


@dataclass
class DiarizationResult:
    turns: list[Turn]
    overlap_regions: list[tuple[float, float]] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


class SpeechToText(Protocol):
    def transcribe(self, audio: np.ndarray, options: dict) -> ASRResult: ...


class SpeakerAttribution(Protocol):
    def diarize(self, audio: np.ndarray, options: dict) -> DiarizationResult: ...
