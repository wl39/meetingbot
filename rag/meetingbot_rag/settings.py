import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=ROOT / ".env.rag", env_file_encoding="utf-8", extra="ignore"
    )
    data_dir: Path = ROOT / ".rag-data"
    source_roots_file: Path = ROOT / "config/source-roots.yaml"
    auth_token_file: Path | None = None
    access_db: Path | None = None
    keyless_login: bool = True
    demo_mode: bool = False
    model_cache_dir: Path | None = None
    access_mode: str = "local"
    public_origin: str = ""
    workspace_url: str = ""
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "testserver"]
    origins: list[str] = ["http://127.0.0.1:8766", "http://localhost:8766"]
    redirect_hosts: list[str] = []
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_revision: str = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    embedding_device: str = "auto"
    chunk_tokens: int = 320
    overlap_tokens: int = 48
    max_files: int = 2000
    max_file_bytes: int = 10 * 1024 * 1024
    max_total_bytes: int = 100 * 1024 * 1024
    max_depth: int = 12
    upload_storage_bytes: int = 1024 * 1024 * 1024
    upload_session_hours: int = 24
    scan_seconds: int = 45
    parse_seconds: int = 15
    xlsx_uncompressed_bytes: int = 50 * 1024 * 1024
    max_sheets: int = 20
    max_rows: int = 20000
    max_columns: int = 100
    max_cells: int = 200000
    encodings: list[str] = ["utf-8-sig"]
    include_hidden: bool = False
    candidates: int = 20
    top_k: int = 6
    min_vector_score: float = 0.76
    max_chunks: int = 25000
    external_llm_allowed: bool = False
    cliproxy_base_url: str = "http://127.0.0.1:8317/v1"
    cliproxy_api_key: str = ""
    llm_response_model: str = ""
    managed_proxy_dir: Path | None = None
    llm_timeout: int = 90
    llm_input_chars: int = 16000
    history_days: int = 30

    @field_validator("workspace_url")
    @classmethod
    def workspace_origin_only(cls, value):
        if not value:
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
            raise ValueError("workspace_url must be an HTTP(S) origin without credentials")
        if url.scheme == "http" and url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("workspace_url requires HTTPS outside loopback")
        return value.rstrip("/")

    def prepare(self):
        def absolute(path):
            path = path.expanduser()
            return path if path.is_absolute() else ROOT / path

        if self.managed_proxy_dir:
            self.managed_proxy_dir = absolute(self.managed_proxy_dir)
        self.data_dir = absolute(self.data_dir).resolve()
        if self.demo_mode and not (self.data_dir / ".demo-instance").is_file():
            raise ValueError("Use scripts/demo.py to prepare isolated demo data")
        self.source_roots_file = absolute(self.source_roots_file)
        self.auth_token_file = absolute(self.auth_token_file or self.data_dir / "admin-token")
        if self.access_mode not in {"local", "remote"}:
            raise ValueError("RAG_ACCESS_MODE must be local or remote")
        if self.access_mode == "remote":
            parsed = urlsplit(self.public_origin)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.hostname not in self.allowed_hosts
                or self.public_origin not in self.origins
            ):
                raise ValueError("remote requires an explicit HTTPS origin and matching hosts/origins")
        if "*" in self.allowed_hosts or "*" in self.origins:
            raise ValueError("Wildcard hosts/origins are not allowed")
        if not 32 <= self.chunk_tokens <= 400 or not 0 <= self.overlap_tokens < self.chunk_tokens:
            raise ValueError("Invalid chunk token limits")
        if not 1 <= self.top_k <= 12:
            raise ValueError("RAG_TOP_K must be between 1 and 12")
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir.chmod(0o700)
        if not self.auth_token_file.is_file():
            raise ValueError("Run scripts/rag.py init locally to create an administrator key")
        if os.name != "nt" and self.auth_token_file.stat().st_mode & 0o077:
            raise ValueError("Administrator key file must have mode 0600")
        if len(self.auth_token_file.read_text(encoding="utf-8").strip()) < 24:
            raise ValueError("Administrator key is too short")

    def fingerprint(self):
        values = {
            k: getattr(self, k)
            for k in (
                "embedding_model",
                "embedding_revision",
                "chunk_tokens",
                "overlap_tokens",
                "encodings",
                "include_hidden",
                "max_rows",
                "max_columns",
                "max_cells",
            )
        }
        values.update(
            parser="4",
            chunker="5",
            normalize=True,
            dimension=384,
            query_template="query: {text}",
            passage_template="passage: {text}",
        )
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest(), values

    def provider_id(self):
        return hashlib.sha256((self.cliproxy_base_url + "|" + self.llm_response_model).encode()).hexdigest()
