"""Composition and shared lifetime of the RAG domain services."""

import shutil
import time

from ..adapters import ParserAdapter, VectorAdapter
from ..db import Database
from ..runtime_settings import RAGSettingsService
from ..sources import UPLOAD_ROOT, RagError, SourceBrowserService
from ..uploads import UploadService
from ..workspace_guides import WorkspaceGuideService
from .ingestion import IngestionService
from .retrieval import EvidenceService, RetrievalService
from .revisions import RevisionService
from .workspaces import WorkspaceService


class Core:
    def __init__(self, settings, model, audit=None):
        self.s, self.model = settings, model
        self.db = Database(settings.data_dir / "registry.sqlite", audit=audit)
        self.runtime_settings = RAGSettingsService(self)
        self.db.recover()
        self.db.execute(
            "DELETE FROM query_runs WHERE created_at<? "
            "AND json_extract(result,'$.status') NOT IN ('queued','processing')",
            (time.time() - settings.history_days * 86400,)
        )
        self.sources = SourceBrowserService(settings)
        # One-time conversion of the original v1 source policy; no document data is rewritten.
        for source in self.db.all("SELECT * FROM sources WHERE policy='default-v1'"):
            try:
                identity = self.sources.identity(source["root_id"])
            except RagError:
                identity = "revoked"
            self.db.execute("UPDATE sources SET policy=? WHERE id=?", (identity, source["id"]))
        self.db.execute(
            "DELETE FROM jobs WHERE workspace_id IS NULL AND created_at<?", (time.time() - 7 * 86400,)
        )
        self.workspaces = WorkspaceService(self.db, self.sources)
        self.guides = WorkspaceGuideService(self)
        self.parser = ParserAdapter(settings)
        self.vectors = VectorAdapter(settings)
        self.revisions = RevisionService(self)
        self.retrieval = RetrievalService(self)
        self.evidence = EvidenceService(self)
        self.ingestion = IngestionService(self)
        self.uploads = UploadService(self)

    def delete(self, wid):
        with self.workspaces.locks[wid]:
            ws = self.workspaces.get(wid, access=False)
            with self.db.transaction():
                self.db.execute("UPDATE workspaces SET deleted=1 WHERE id=?", (wid,))
                self.db.execute("UPDATE jobs SET cancel=1 WHERE workspace_id=?", (wid,))
            self.vectors.call("delete_workspace", wid)
            path = self.s.data_dir / "workspaces" / wid
            if path.exists():
                shutil.rmtree(path)
            uploaded = ws["source"] and ws["source"]["root_id"] == UPLOAD_ROOT
            if uploaded:
                self.uploads.remove_files(ws["source"]["relative_path"])
            with self.db.transaction():
                self.db.execute("DELETE FROM upload_sessions WHERE workspace_id=?", (wid,))
                for table in (
                    "query_runs",
                    "document_versions",
                    "documents",
                    "revisions",
                    "jobs",
                    "sources",
                    "knowledge_bases",
                ):
                    self.db.execute(f"DELETE FROM {table} WHERE workspace_id=?", (wid,))
                self.db.execute("DELETE FROM workspaces WHERE id=?", (wid,))
        return {"deleted": True, "workspace_id": wid, "source_preserved": not uploaded}

    def close(self):
        self.ingestion.close()
        self.vectors.close()
        self.db.close()
