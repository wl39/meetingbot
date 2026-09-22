"""Workspace-scoped reference preferences, never privileged model instructions."""

import hashlib
import time
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .sources import RagError

MAX_GUIDE_CHARS = 4000


class GuideUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=0)
    content: str = Field(max_length=MAX_GUIDE_CHARS)
    enabled: bool

    @field_validator("content")
    @classmethod
    def clean_content(cls, value):
        value = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\t" for c in value):
            raise ValueError("Control characters are not allowed")
        return value


def content_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()


class WorkspaceGuideService:
    def __init__(self, core):
        self.c = core

    def get(self, wid):
        with self.c.workspaces.locks[wid]:
            self.c.workspaces.get(wid)
            row = self.c.db.one("SELECT * FROM workspace_guides WHERE workspace_id=?", (wid,))
            return {
                **(
                    row
                    or {
                        "workspace_id": wid,
                        "version": 0,
                        "content": "",
                        "enabled": False,
                        "content_hash": content_hash(""),
                        "updated_at": None,
                    }
                ),
                "enabled": bool(row and row["enabled"]),
                "max_chars": MAX_GUIDE_CHARS,
            }

    def save(self, wid, body):
        with self.c.workspaces.locks[wid], self.c.db.transaction():
            current = self.get(wid)
            if current["version"] != body.expected_version:
                raise RagError(
                    "GUIDE_CHANGED",
                    "다른 화면에서 지침서가 변경되었습니다. 최신 내용을 확인한 뒤 다시 저장하세요.",
                    409,
                )
            self.c.db.execute(
                "INSERT INTO workspace_guides VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(workspace_id) DO UPDATE SET version=excluded.version, "
                "content=excluded.content, enabled=excluded.enabled, "
                "content_hash=excluded.content_hash, updated_at=excluded.updated_at",
                (
                    wid,
                    current["version"] + 1,
                    body.content,
                    bool(body.enabled and body.content),
                    content_hash(body.content),
                    time.time(),
                ),
            )
            return self.get(wid)


def guide_reference(guide):
    """Only call for the final writing stage. No effect on retrieval or authorization."""
    if not guide["enabled"] or not guide["content"]:
        return {}
    return {"workspace_guide": {"content": guide["content"]}}


def guide_provenance(guide):
    return {
        "version": guide["version"],
        "content_hash": guide["content_hash"],
        "included": bool(guide["enabled"] and guide["content"]),
    }
