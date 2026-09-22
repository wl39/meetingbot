from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class WordTiming(BaseModel):
    text: str
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("word end_ms must be > start_ms")
        return self


class UtteranceEvent(BaseModel):
    schema_version: Literal[1] = 1
    event_id: str = Field(default_factory=lambda: uid("evt"))
    session_id: str
    meeting_id: str | None = None
    utterance_id: str = Field(default_factory=lambda: uid("utt"))
    revision: int = Field(default=1, ge=1)
    speaker_id: str | None = None
    speaker_status: Literal["unknown", "provisional", "assigned", "manual"] = "unknown"
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    words: list[WordTiming] = Field(default_factory=list)
    status: Literal["partial", "stable", "corrected", "retracted"] = "stable"
    source: Literal["audio"] = "audio"
    input_mode: Literal["file", "microphone"]
    addressed_to_ai: bool = False
    overlap: bool = False
    manual_fields: list[str] = Field(default_factory=list)
    replaces_utterance_ids: list[str] = Field(default_factory=list)
    changed_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be >= start_ms")
        return self
