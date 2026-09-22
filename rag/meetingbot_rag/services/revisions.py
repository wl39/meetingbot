"""Revision snapshots, validation, activation, and retention."""

import hashlib
import json
import shutil
import time

from ..db import dumps, open_database
from ..sources import RagError


class RevisionService:
    def __init__(self, core):
        self.c = core

    def resolve(self, wid, revision_id=None):
        ws = self.c.workspaces.get(wid)
        revision_id = revision_id or ws["active_revision_id"]
        rev = self.c.db.one(
            "SELECT * FROM revisions WHERE id=? AND workspace_id=? AND state='READY'", (revision_id, wid)
        )
        if not rev:
            raise RagError("REVISION_NOT_READY", "사용 가능한 자료 버전이 없습니다.", 409)
        return ws, rev

    def path(self, wid, rid):
        return self.c.s.data_dir / "workspaces" / wid / "revisions" / rid

    def pin(self, wid, rid, pinned):
        c = self.c
        with c.workspaces.locks[wid]:
            c.workspaces.get(wid)
            if not c.db.one("SELECT id FROM revisions WHERE id=? AND workspace_id=?", (rid, wid)):
                raise RagError("NOT_FOUND", status=404)
            c.db.execute(
                "UPDATE revisions SET pinned=? WHERE id=? AND workspace_id=?", (int(pinned), rid, wid)
            )
        return {"workspace_id": wid, "revision_id": rid, "pinned": pinned}

    def remove(self, wid, rid):
        c = self.c
        with c.workspaces.locks[wid]:
            ws = c.workspaces.get(wid)
            rev = c.db.one("SELECT * FROM revisions WHERE id=? AND workspace_id=?", (rid, wid))
            if not rev:
                raise RagError("NOT_FOUND", status=404)
            running = c.db.one(
                "SELECT id FROM jobs WHERE workspace_id=? AND state IN ('QUEUED','RUNNING')", (wid,)
            )
            pending_question = c.db.one(
                "SELECT id FROM query_runs WHERE workspace_id=? AND revision_id=? "
                "AND json_extract(result,'$.status') IN ('queued','processing') LIMIT 1", (wid, rid)
            )
            if rid == ws["active_revision_id"] or rev["pinned"] or running or pending_question:
                raise RagError(
                    "REVISION_PROTECTED", "활성·보존 버전 또는 자료 준비 중에는 삭제할 수 없습니다.", 409
                )
            c.vectors.call("drop", wid, rid)
            path = self.path(wid, rid)
            if path.exists():
                shutil.rmtree(path)
            with c.db.transaction():
                c.db.execute("DELETE FROM query_runs WHERE workspace_id=? AND revision_id=?", (wid, rid))
                c.db.execute("DELETE FROM jobs WHERE workspace_id=? AND revision_id=?", (wid, rid))
                c.db.execute("DELETE FROM revisions WHERE workspace_id=? AND id=?", (wid, rid))
                referenced = set()
                for remaining in c.db.all("SELECT manifest FROM revisions WHERE workspace_id=?", (wid,)):
                    referenced.update(
                        d["document_version_id"]
                        for d in json.loads(remaining["manifest"] or "{}").get("documents", [])
                    )
                for dv in c.db.all("SELECT id,snapshot FROM document_versions WHERE workspace_id=?", (wid,)):
                    if dv["id"] not in referenced:
                        (c.s.data_dir / dv["snapshot"]).unlink(missing_ok=True)
                        (c.s.data_dir / dv["snapshot"]).with_suffix(".view.sqlite").unlink(missing_ok=True)
                        c.db.execute(
                            "DELETE FROM document_versions WHERE id=? AND workspace_id=?", (dv["id"], wid)
                        )
        return {"workspace_id": wid, "revision_id": rid, "deleted": True}

    def activate(self, wid, rid, job_id, count, manifest):
        c = self.c
        with c.workspaces.locks[wid]:
            c.ingestion.check(job_id)
            c.workspaces.get(wid)
            revpath = self.path(wid, rid)
            with open_database(revpath / "keyword.sqlite") as db:
                rows = db.execute("SELECT payload FROM chunks").fetchall()
                fts_count = db.execute("SELECT count(*) FROM search").fetchone()[0]
            if len(rows) != count or fts_count != count or c.vectors.call("count", wid, rid) != count:
                raise RagError("INDEX_VALIDATION_FAILED")
            for row in rows:
                payload = json.loads(row[0])
                if payload["workspace_id"] != wid or payload["revision_id"] != rid:
                    raise RagError("EVIDENCE_SCOPE_INVALID")
            for doc in manifest["documents"]:
                dv = c.db.one(
                    "SELECT * FROM document_versions WHERE id=? AND workspace_id=?",
                    (doc["document_version_id"], wid),
                )
                snapshot = c.s.data_dir / dv["snapshot"]
                if hashlib.sha256(snapshot.read_bytes()).hexdigest() != dv["content_hash"]:
                    raise RagError("SNAPSHOT_VALIDATION_FAILED")
            (revpath / "manifest.json").write_text(dumps(manifest), encoding="utf-8")
            with c.db.transaction():
                c.ingestion.check(job_id)
                c.workspaces.get(wid)
                c.db.execute(
                    "UPDATE revisions SET state='READY',manifest=? WHERE id=? AND workspace_id=?",
                    (dumps(manifest), rid, wid),
                )
                c.db.execute(
                    "UPDATE knowledge_bases SET active_revision_id=? WHERE workspace_id=?", (rid, wid)
                )
                c.db.execute(
                    "UPDATE jobs SET state='READY',updated_at=?,result=? WHERE id=?",
                    (time.time(), dumps(manifest), job_id),
                )
