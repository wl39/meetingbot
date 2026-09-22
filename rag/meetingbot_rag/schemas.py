"""Validated public inputs shared by the RAG feature routers."""

from pydantic import BaseModel, Field


class SourceInput(BaseModel):
    root_id: str = Field(min_length=1, max_length=100)
    relative_path: str = Field(default="", max_length=2048)


class WorkspaceInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    root_id: str | None = Field(default=None, max_length=100)
    relative_path: str = Field(default="", max_length=2048)


class WorkspacePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    external_llm_approved: bool | None = None
    provider_id: str | None = None


class RevisionPatch(BaseModel):
    pinned: bool


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=8000)
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    top_k: int | None = Field(default=None, ge=1, le=12)


class Login(BaseModel):
    key: str = Field(min_length=1, max_length=256)


class IndexInput(BaseModel):
    allow_review: bool = False
