"""Workspace registration, source access, and public job summaries."""

import json
import threading
import time
from collections import defaultdict

from ..db import uid
from ..sources import UPLOAD_ROOT, RagError


class WorkspaceService:
    def __init__(self, db, sources):
        self.db, self.sources = db, sources
        self.locks = defaultdict(threading.RLock)

    def get(self, wid, access=True):
        item = self.db.one(
            "SELECT w.*, k.id knowledge_base_id, k.active_revision_id FROM workspaces w "
            "JOIN knowledge_bases k ON k.workspace_id=w.id WHERE w.id=? AND w.deleted=0",
            (wid,),
        )
        if not item:
            raise RagError("NOT_FOUND", "워크스페이스를 찾을 수 없습니다.", 404)
        item["source"] = self.db.one("SELECT * FROM sources WHERE workspace_id=?", (wid,))
        if item["source"]:
            uploaded = item["source"]["root_id"] == UPLOAD_ROOT
            item["source"]["kind"] = "upload" if uploaded else "server"
            if uploaded:
                upload = self.db.one("SELECT folder_name FROM upload_sessions WHERE workspace_id=?", (wid,))
                item["source"]["label"] = upload["folder_name"] if upload else "업로드한 자료"
        if access and item["source"]:
            self.sources.validate_source(item["source"])
        item["document_count"] = 0
        item["state"] = "REGISTERED"
        if item["active_revision_id"]:
            rev = self.db.one(
                "SELECT manifest FROM revisions WHERE id=? AND workspace_id=?",
                (item["active_revision_id"], wid),
            )
            item["document_count"] = (
                len(json.loads(rev["manifest"] or "{}").get("documents", [])) if rev else 0
            )
            item["state"] = "READY"
        item["latest_job"] = self.db.one(
            "SELECT * FROM jobs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 1", (wid,)
        )
        if item["latest_job"]:
            item["latest_job"] = job_public(item["latest_job"])
        return item

    def list(self):
        out = []
        for row in self.db.all("SELECT id FROM workspaces WHERE deleted=0 ORDER BY created_at"):
            item = self.get(row["id"], access=False)
            try:
                if item["source"]:
                    self.sources.validate_source(item["source"])
                item["access_state"] = "AVAILABLE"
            except RagError as error:
                item["access_state"] = error.code
            out.append(item)
        return out

    def create(self, name, description, root_id=None, relative_path=""):
        if root_id:
            self.sources.validate(root_id, relative_path)
        wid = uid()
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO workspaces(id,name,description,created_at) VALUES(?,?,?,?)",
                (wid, name, description, time.time()),
            )
            self.db.execute("INSERT INTO knowledge_bases(id,workspace_id) VALUES(?,?)", (uid(), wid))
            if root_id:
                self.db.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?)",
                    (uid(), wid, root_id, relative_path, self.sources.identity(root_id)),
                )
        return self.get(wid)

    def source(self, wid, root_id, relative_path):
        self.sources.validate(root_id, relative_path)
        with self.locks[wid], self.db.transaction():
            item = self.get(wid, access=False)
            if item["source"]:
                raise RagError(
                    "SOURCE_ALREADY_CONNECTED",
                    "이 단계에서는 워크스페이스마다 하나의 폴더만 연결합니다.",
                    409,
                )
            self.db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?)",
                (uid(), wid, root_id, relative_path, self.sources.identity(root_id)),
            )
        return self.get(wid)


def job_public(row):
    return {
        **{k: v for k, v in row.items() if k not in {"payload", "result", "idempotency_key"}},
        "job_id": row["id"],
        "result": json.loads(row["result"] or "{}"),
    }
