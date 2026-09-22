"""Persisted retrieval preferences and immutable settings for each index build."""

import json
import time

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .db import dumps
from .sources import RagError


class RAGConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chunk_tokens: int = Field(ge=32, le=400)
    overlap_tokens: int = Field(ge=0, le=399)
    top_k: int = Field(ge=1, le=12)

    @model_validator(mode="after")
    def overlap_fits_chunk(self):
        if self.overlap_tokens >= self.chunk_tokens:
            raise ValueError("overlap_tokens must be smaller than chunk_tokens")
        return self


class RAGSettingsUpdate(RAGConfig):
    expected_version: int = Field(ge=0)


class RAGSettingsService:
    def __init__(self, core):
        self.c = core

    def snapshot(self):
        row = self.c.db.one("SELECT * FROM rag_settings WHERE id=1")
        config = RAGConfig.model_validate(
            json.loads(row["body"])
            if row
            else {key: getattr(self.c.s, key) for key in RAGConfig.model_fields}
        )
        return self.c.s.model_copy(update=config.model_dump()), row["version"] if row else 0

    def public(self):
        # Read the version, values and index state in one consistent database snapshot.
        with self.c.db.transaction():
            settings, version = self.snapshot()
            row = self.c.db.one("SELECT updated_at FROM rag_settings WHERE id=1")
            fingerprint, _ = settings.fingerprint()
            workspaces = []
            for item in self.c.db.all(
                "SELECT w.id workspace_id,w.name,k.active_revision_id,r.fingerprint,r.manifest,"
                "EXISTS(SELECT 1 FROM sources s WHERE s.workspace_id=w.id) has_source,"
                "EXISTS(SELECT 1 FROM jobs j WHERE j.workspace_id=w.id "
                "AND j.state IN ('QUEUED','RUNNING')) indexing "
                "FROM workspaces w JOIN knowledge_bases k ON k.workspace_id=w.id "
                "LEFT JOIN revisions r ON r.id=k.active_revision_id WHERE w.deleted=0 "
                "ORDER BY w.created_at"
            ):
                manifest = json.loads(item.pop("manifest") or "{}")
                saved_fingerprint = item.pop("fingerprint")
                workspaces.append(
                    {
                        **item,
                        "has_source": bool(item["has_source"]),
                        "indexing": bool(item["indexing"]),
                        "chunk_count": manifest.get("chunks", 0),
                        "requires_reindex": bool(
                            item["active_revision_id"] and saved_fingerprint != fingerprint
                        ),
                    }
                )
            return {
                "version": version,
                **{key: getattr(settings, key) for key in RAGConfig.model_fields},
                "updated_at": row["updated_at"] if row else None,
                "limits": {
                    "chunk_tokens": {"min": 32, "max": 400},
                    "overlap_tokens": {"min": 0, "max": 399},
                    "top_k": {"min": 1, "max": 12},
                },
                "reindex_required": any(item["requires_reindex"] for item in workspaces),
                "workspaces": workspaces,
            }

    def save(self, update):
        with self.c.db.transaction():
            _, version = self.snapshot()
            if update.expected_version != version:
                raise RagError(
                    "SETTINGS_VERSION_CONFLICT",
                    "다른 창에서 검색 설정이 변경되었습니다. 새로고침 후 다시 저장하세요.",
                    409,
                )
            config = update.model_dump(exclude={"expected_version"})
            self.c.db.execute(
                "INSERT INTO rag_settings(id,version,body,updated_at) VALUES(1,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET version=excluded.version,body=excluded.body,"
                "updated_at=excluded.updated_at",
                (version + 1, dumps(config), time.time()),
            )
        return self.public()
