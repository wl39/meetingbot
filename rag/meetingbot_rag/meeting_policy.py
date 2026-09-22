"""Versioned, administrator-controlled meeting scheduling and scope policy."""

import json
import time

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .db import dumps
from .sources import RagError


class ScopeProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    description: str = Field(default="", max_length=600)
    included_topics: list[str] = Field(default_factory=list, max_length=12)
    excluded_topics: list[str] = Field(default_factory=lambda: ["개인 프로젝트", "일상 대화"], max_length=12)
    aliases: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("included_topics", "excluded_topics", "aliases")
    @classmethod
    def short_terms(cls, values):
        if any(not value.strip() or len(value) > 60 for value in values):
            raise ValueError("Scope terms must contain 1 to 60 characters")
        return list(dict.fromkeys(value.strip() for value in values))

    @model_validator(mode="after")
    def bounded(self):
        if len(dumps(self.model_dump())) > 1600:
            raise ValueError("Combined scope profile must fit within 1600 characters")
        return self


class MeetingPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    priority_response_target_seconds: int = Field(default=20, ge=3, le=120)
    pressure_ratio: float = Field(default=0.5, gt=0, lt=1)
    protect_ratio: float = Field(default=0.8, gt=0, lt=1)
    recovery_ratio: float = Field(default=0.4, ge=0, lt=1)
    recovery_seconds: float = Field(default=3, ge=0, le=30)
    context_wait_seconds: float = Field(default=2, ge=0, le=5)
    filter_model: str = Field(default="", max_length=200)
    filter_timeout_seconds: float = Field(default=8, ge=1, le=15)
    generation_timeout_seconds: float = Field(default=20, ge=1, le=60)
    scope_profile: ScopeProfile = Field(default_factory=ScopeProfile)

    @field_validator("filter_model")
    @classmethod
    def valid_model(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Invalid model name")
        return value.strip()

    @model_validator(mode="after")
    def thresholds(self):
        if not self.recovery_ratio < self.pressure_ratio < self.protect_ratio:
            raise ValueError("Require recovery < pressure < protect")
        return self


class PolicyUpdate(MeetingPolicy):
    expected_version: int = Field(ge=0)


class MeetingPolicies:
    def __init__(self, core):
        self.c = core

    def get(self, wid):
        workspace = self.c.workspaces.get(wid)
        row = self.c.db.one("SELECT * FROM meeting_policies WHERE workspace_id=?", (wid,))
        if row:
            policy = MeetingPolicy.model_validate(json.loads(row["body"]))
        else:
            description = " · ".join(x for x in (workspace["name"], workspace.get("description")) if x)
            policy = MeetingPolicy(scope_profile=ScopeProfile(description=description[:600]))
        return {"version": row["version"] if row else 0, **policy.model_dump()}

    def save(self, wid, body, principal):
        if not principal.manages_data:
            raise RagError("ROLE_DENIED", status=403)
        with self.c.db.transaction():
            current = self.get(wid)
            if body.expected_version != current["version"]:
                raise RagError(
                    "SETTINGS_VERSION_CONFLICT", "설정이 변경되었습니다. 새로고침 후 저장하세요.", 409
                )
            if body.filter_model != current["filter_model"] and principal.role != "superadmin":
                raise RagError("ROLE_DENIED", "필터 모델은 슈퍼관리자가 변경할 수 있습니다.", 403)
            values = body.model_dump(exclude={"expected_version"})
            self.c.db.execute(
                "INSERT INTO meeting_policies VALUES(?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET "
                "version=excluded.version,body=excluded.body,updated_at=excluded.updated_at",
                (wid, current["version"] + 1, dumps(values), time.time()),
            )
        return self.get(wid)
