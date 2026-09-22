from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Options(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["small", "large-v3-turbo"] = "small"
    language: Literal["ko"] = "ko"
    num_speakers: int | None = Field(default=None, ge=1, le=8)
    retain_audio: bool = False


class Correction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=1)
    text: str | None = Field(default=None, max_length=10000)
    speaker_id: str | None = None


class SpeakerPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)


class FileUploadStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    options: Options = Field(default_factory=Options)


class StartFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["start"]
    stream_id: str = Field(min_length=1, max_length=80)
    sample_rate: int = Field(ge=8000, le=96000)
    channels: Literal[1] = 1
    encoding: Literal["f32le"] = "f32le"


class StopFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["stop"]
    last_sequence: int = Field(ge=-1)
