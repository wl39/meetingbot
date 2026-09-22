"""Administrator-managed connection settings and immutable prompt revisions."""

import hashlib
import json
import math
import time
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .db import dumps, uid
from .settings import ROOT
from .sources import RagError


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = "http://127.0.0.1:8317/v1"
    api_key: str = Field(default="", max_length=4096)
    default_model: str = Field(default="", max_length=200)
    enabled: bool = False
    max_output_tokens: int = Field(default=4096, ge=256, le=16384)
    timeout_seconds: int = Field(default=90, ge=10, le=180)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: str | None = None
    input_chars: int = Field(default=24000, ge=4000, le=64000)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/v1"}
            or any(ord(c) < 33 for c in value)
            or "\\" in value
        ):
            raise ValueError("Use an HTTP(S) CLIProxyAPI origin with /v1, no URL credentials or query")
        try:
            parsed.port
        except ValueError:
            raise ValueError("Invalid port") from None
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), "/v1", "", ""))

    @field_validator("api_key", "default_model")
    @classmethod
    def no_controls(cls, value):
        value = value.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Control characters are not allowed")
        return value

    @field_validator("reasoning_effort")
    @classmethod
    def effort(cls, value):
        if value not in {None, "none", "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("Invalid reasoning effort")
        return value

    @field_validator("temperature")
    @classmethod
    def finite(cls, value):
        if value is not None and not math.isfinite(value):
            raise ValueError("Temperature must be finite")
        return value


class LLMSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    base_url: str | None = None
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    default_model: str | None = Field(default=None, max_length=200)
    enabled: bool | None = None
    max_output_tokens: int | None = Field(default=None, ge=256, le=16384)
    timeout_seconds: int | None = Field(default=None, ge=10, le=180)
    temperature: float | None = Field(default=None, ge=0, le=2)
    reasoning_effort: str | None = None
    input_chars: int | None = Field(default=None, ge=4000, le=64000)

    @model_validator(mode="after")
    def required_values(self):
        for key in self.model_fields_set - {"api_key", "temperature", "reasoning_effort"}:
            if getattr(self, key) is None:
                raise ValueError("Required setting cannot be null")
        return self


class PromptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=20, max_length=12000)
    note: str = Field(default="", max_length=500)
    activate: bool = False
    expected_active_id: str

    @field_validator("name", "content")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value.strip()


class PromptActivation(BaseModel):
    expected_active_id: str


class PromptPreview(BaseModel):
    content: str | None = Field(default=None, min_length=20, max_length=12000)
    case: str = Field(default="supported", pattern="^(supported|related|missing|conflict|injection)$")
    model: str | None = Field(default=None, max_length=200)


class ModelCheck(BaseModel):
    model: str | None = Field(default=None, max_length=200)


class LLMSettingsService:
    def __init__(self, core):
        self.c = core

    def snapshot(self):
        row = self.c.db.one("SELECT * FROM llm_settings WHERE id=1")
        if row:
            return LLMConfig.model_validate(json.loads(row["body"])), row["version"]
        s = self.c.s
        # Legacy .env is an initial default only. Web saves survive deployments.
        return LLMConfig(
            base_url=s.cliproxy_base_url,
            api_key=s.cliproxy_api_key,
            default_model=s.llm_response_model,
            enabled=s.external_llm_allowed,
            timeout_seconds=max(10, min(180, s.llm_timeout)),
        ), 0

    @staticmethod
    def connection_id(config):
        return hashlib.sha256((config.base_url + "|" + config.api_key).encode()).hexdigest()

    @staticmethod
    def provider_id(config):
        # Model/URL changes invalidate workspace transfer consent; key rotation doesn't.
        return hashlib.sha256((config.base_url + "|" + config.default_model).encode()).hexdigest()

    def public(self):
        config, version = self.snapshot()
        body = config.model_dump(exclude={"api_key"})
        body.update(
            version=version, api_key_present=bool(config.api_key), provider_id=self.provider_id(config)
        )
        checked = self.c.db.one(
            "SELECT result,checked_at FROM llm_model_checks WHERE provider_id=?",
            (self.check_id(config, config.default_model),),
        )
        body["last_check"] = json.loads(checked["result"]) if checked else None
        return body

    @classmethod
    def check_id(cls, config, model):
        values = config.model_dump(exclude={"enabled", "input_chars", "default_model"})
        return hashlib.sha256((dumps(values) + "|" + model).encode()).hexdigest()

    def save(self, update):
        with self.c.db.transaction():
            old, version = self.snapshot()
            if version != update.expected_version:
                raise RagError(
                    "SETTINGS_CHANGED", "다른 화면에서 설정이 변경됐습니다. 최신 설정을 불러오세요.", 409
                )
            changes = update.model_dump(exclude_unset=True, exclude={"expected_version", "clear_api_key"})
            if changes.get("api_key") in {None, ""}:
                changes.pop("api_key", None)
            try:
                config = LLMConfig.model_validate({**old.model_dump(), **changes})
            except ValueError:
                raise RagError(
                    "INVALID_LLM_SETTINGS", "연결 주소와 모델 설정의 형식·범위를 확인하세요.", 422
                ) from None
            if update.clear_api_key:
                config.api_key = ""
            if config.base_url != old.base_url and not changes.get("api_key"):
                # Never send an old connection's key to an administrator's new address.
                config.api_key = ""
            if config.base_url != old.base_url and "default_model" not in changes:
                config.default_model = ""
            self.c.db.execute(
                "INSERT INTO llm_settings(id,version,body,updated_at) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version,body=excluded.body,updated_at=excluded.updated_at",
                (version + 1, dumps(config.model_dump()), time.time()),
            )
            if self.provider_id(config) != self.provider_id(old):
                self.c.db.execute("UPDATE workspaces SET consent=NULL")
        return self.public()

    def catalog(self):
        config, _ = self.snapshot()
        row = self.c.db.one(
            "SELECT * FROM llm_model_catalog WHERE connection_id=?", (self.connection_id(config),)
        )
        return {
            "models": json.loads(row["models"]) if row else [],
            "fetched_at": row["fetched_at"] if row else None,
            "connection_id": self.connection_id(config),
        }

    def cache_catalog(self, config, models):
        with self.c.db.transaction():
            current, _ = self.snapshot()
            if self.connection_id(current) != self.connection_id(config):
                raise RagError("SETTINGS_CHANGED", "모델 목록을 가져오는 동안 연결 설정이 변경됐습니다.", 409)
            self.c.db.execute(
                "INSERT INTO llm_model_catalog VALUES(?,?,?) ON CONFLICT(connection_id) "
                "DO UPDATE SET models=excluded.models,fetched_at=excluded.fetched_at",
                (self.connection_id(config), dumps(models), time.time()),
            )
        return self.catalog()


class PromptService:
    def __init__(self, core):
        self.c = core
        with core.db.transaction():
            if not core.db.one("SELECT * FROM prompt_settings WHERE id=1"):
                content = (ROOT / "prompts/rag_answer.md").read_text(encoding="utf-8").strip()
                pid = self._insert("회의봇 근거 기반 답변", content, "기본 한국어 RAG 답변 프롬프트")
                core.db.execute("INSERT INTO prompt_settings VALUES(1,?)", (pid,))

    def _insert(self, name, content, note, restored_from=None):
        pid = uid()
        sequence = self.c.db.one("SELECT COALESCE(MAX(sequence),0)+1 n FROM prompt_versions")["n"]
        self.c.db.execute(
            "INSERT INTO prompt_versions VALUES(?,?,?,?,?,?,?,?)",
            (
                pid,
                sequence,
                name,
                content,
                hashlib.sha256(content.encode()).hexdigest(),
                note,
                time.time(),
                restored_from,
            ),
        )
        return pid

    def active(self):
        row = self.c.db.one("SELECT active_version_id FROM prompt_settings WHERE id=1")
        return self.get(row["active_version_id"])

    def get(self, pid):
        row = self.c.db.one("SELECT * FROM prompt_versions WHERE id=?", (pid,))
        if not row:
            raise RagError("PROMPT_NOT_FOUND", "프롬프트 버전을 찾을 수 없습니다.", 404)
        return row

    def list(self):
        active = self.active()
        return {
            "active_id": active["id"],
            "versions": self.c.db.all(
                "SELECT id,sequence,name,content_hash,note,created_at,restored_from_id FROM prompt_versions ORDER BY sequence DESC LIMIT 200"
            ),
        }

    def save(self, body):
        with self.c.db.transaction():
            if self.active()["id"] != body.expected_active_id:
                raise RagError("PROMPT_CHANGED", "활성 프롬프트가 변경됐습니다. 최신 버전을 불러오세요.", 409)
            pid = self._insert(body.name, body.content, body.note)
            if body.activate:
                self.c.db.execute("UPDATE prompt_settings SET active_version_id=? WHERE id=1", (pid,))
        return {"prompt": self.get(pid), "active_id": self.active()["id"]}

    def activate(self, pid, expected_active_id, restore=False):
        with self.c.db.transaction():
            original = self.get(pid)
            if self.active()["id"] != expected_active_id:
                raise RagError("PROMPT_CHANGED", "활성 프롬프트가 변경됐습니다. 최신 버전을 불러오세요.", 409)
            if restore:
                pid = self._insert(
                    original["name"],
                    original["content"],
                    f"버전 {original['sequence']}에서 복원",
                    original["id"],
                )
            self.c.db.execute("UPDATE prompt_settings SET active_version_id=? WHERE id=1", (pid,))
        return {"prompt": self.get(pid), "active_id": pid}
