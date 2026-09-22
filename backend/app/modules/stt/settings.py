import os
import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="STT_", env_file=ROOT / ".env", extra="ignore")
    engine: Literal["real", "fake"] = "real"
    asr_backend: Literal["auto", "mlx", "faster-whisper"] = "auto"
    default_model: Literal["small", "large-v3-turbo"] = "small"
    data_dir: Path = ROOT / ".runtime"
    origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:8765"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    public_origin: str | None = None
    redirect_hosts: list[str] = []
    max_file_bytes: int = 4 * 1024 * 1024 * 1024
    max_file_seconds: int = 18000
    file_chunk_seconds: int = 120
    max_live_seconds: int = 300
    asr_interval: float = 2.0
    diar_interval: float = 20.0
    diarization_device: Literal["auto", "cpu", "mps", "cuda"] = "auto"
    diarization_cpu_threads: int = Field(default=0, ge=0, le=128)
    diarization_batch_size: int = Field(default=8, ge=1, le=64)
    rag_base_url: str = "http://127.0.0.1:8766"
    rag_token_file: Path | None = None
    rag_public_url: str | None = None
    access_db: Path | None = None
    keyless_login: bool = True
    demo_mode: bool = False
    demo_daily_jobs: int = Field(default=100, ge=1, le=1000)
    demo_jobs_per_visitor: int = Field(default=3, ge=1, le=20)

    @field_validator("rag_base_url")
    @classmethod
    def loopback_rag_only(cls, value):
        url = urlsplit(value)
        if (
            url.scheme != "http"
            or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("rag_base_url must be a loopback HTTP origin")
        if url.port is None:
            raise ValueError("rag_base_url must include a port")
        return value.rstrip("/")

    @field_validator("rag_public_url")
    @classmethod
    def rag_link_only(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("rag_public_url must be an HTTP(S) origin")
        return value.rstrip("/")

    @field_validator("public_origin")
    @classmethod
    def https_origin_only(cls, value):
        if value is None:
            return value
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.path not in ("", "/")
            or url.query
            or url.fragment
        ):
            raise ValueError("public_origin must be an HTTPS origin without a path or credentials")
        return value.rstrip("/")

    def prepare(self):
        self.data_dir = self.data_dir.resolve()
        if self.demo_mode:
            # An existing private instance must never become anonymous by one env toggle.
            if not (self.data_dir / ".demo-instance").is_file():
                raise ValueError("Use scripts/demo.py to prepare an isolated demo data directory")
            self.max_file_bytes = min(self.max_file_bytes, 20 * 1024 * 1024)
            self.max_file_seconds = min(self.max_file_seconds, 180)
            self.max_live_seconds = min(self.max_live_seconds, 180)
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.data_dir, 0o700)
        for name in ("tmp", "audio", "models"):
            (self.data_dir / name).mkdir(exist_ok=True, mode=0o700)

    def local_token(self):
        path = self.data_dir / "local-token"
        if not path.exists():
            path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
        return path.read_text().strip()
