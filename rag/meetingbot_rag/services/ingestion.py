"""Bounded background ingestion and document indexing."""

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path, PurePosixPath

from ..adapters import chunk_document
from ..db import dumps, open_database, uid
from ..sources import RagError
from .retrieval import keyword_text
from .workspaces import job_public


class IngestionService:
    def __init__(self, core):
        self.c = core
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-ingestion")
        self.stop = threading.Event()
        self.heartbeat_thread = threading.Thread(target=self.heartbeat, daemon=True)
        self.heartbeat_thread.start()

    def heartbeat(self):
        while not self.stop.wait(2):
            self.c.db.execute("UPDATE jobs SET heartbeat=? WHERE state='RUNNING'", (time.time(),))

    def check(self, jid):
        job = self.c.db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        if not job or job["cancel"] or self.stop.is_set():
            raise RagError("CANCELLED", "작업을 취소했습니다.")
        if job["workspace_id"]:
            self.c.workspaces.get(job["workspace_id"])
        return job

    def progress(self, jid, result):
        self.c.db.record("rag.job_progress", job_id=jid, stage=result.get("stage"))
        self.c.db.execute(
            "UPDATE jobs SET result=?,updated_at=?,heartbeat=? WHERE id=?",
            (dumps(result), time.time(), time.time(), jid),
        )

    def create(self, wid=None, payload=None, idempotency_key=None, allow_review=False):
        c = self.c
        with c.db.transaction():
            if wid:
                ws = c.workspaces.get(wid)
                if not ws["source"]:
                    raise RagError("SOURCE_REQUIRED", "먼저 서버 폴더를 연결하세요.")
                if idempotency_key:
                    previous = c.db.one(
                        "SELECT * FROM jobs WHERE workspace_id=? AND idempotency_key=?",
                        (wid, idempotency_key),
                    )
                    if previous:
                        return job_public(previous)
                current = c.db.one(
                    "SELECT * FROM jobs WHERE workspace_id=? AND state IN ('QUEUED','RUNNING')", (wid,)
                )
                if current:
                    return job_public(current)
                payload = {"root_id": ws["source"]["root_id"], "relative_path": ws["source"]["relative_path"]}
            else:
                c.sources.validate(payload["root_id"], payload["relative_path"])
            queued = c.db.one("SELECT count(*) n FROM jobs WHERE state IN ('QUEUED','RUNNING')")["n"]
            if queued >= 4:
                raise RagError("JOB_QUEUE_FULL", "대기 중인 작업이 많습니다. 잠시 후 재시도하세요.", 429)
            jid, rid = uid(), uid() if wid else None
            build_settings, _ = c.runtime_settings.snapshot()
            fingerprint, config = build_settings.fingerprint()
            if allow_review:
                # Never reuse permissive parsing in an ordinary strict build.
                fingerprint = hashlib.sha256((fingerprint + ":review-v1").encode()).hexdigest()
                config["allow_review"] = True
            if wid:
                c.db.execute(
                    "INSERT INTO revisions(id,workspace_id,state,fingerprint,config,created_at) VALUES(?,?,?,?,?,?)",
                    (rid, wid, "REGISTERED", fingerprint, dumps(config), time.time()),
                )
            c.db.execute(
                "INSERT INTO jobs(id,workspace_id,revision_id,kind,state,created_at,updated_at,heartbeat,payload,result,idempotency_key) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    jid,
                    wid,
                    rid,
                    "INDEX" if wid else "PREVIEW",
                    "QUEUED",
                    time.time(),
                    time.time(),
                    time.time(),
                    dumps(payload),
                    "{}",
                    idempotency_key,
                ),
            )
        c.db.record("rag.job_created", job_id=jid, workspace_id=wid, revision_id=rid, state="QUEUED")
        self.executor.submit(copy_context().run, self.run, jid)
        return job_public(c.db.one("SELECT * FROM jobs WHERE id=?", (jid,)))

    def run(self, jid):
        c = self.c
        job = c.db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        wid, rid = job["workspace_id"], job["revision_id"]
        started = time.monotonic()
        result = {"stage": "SCANNING", "queue_ms": round((time.time() - job["created_at"]) * 1000)}
        try:
            self.check(jid)
            c.db.execute("UPDATE jobs SET state='RUNNING' WHERE id=?", (jid,))
            if rid:
                c.db.execute("UPDATE revisions SET state='SCANNING' WHERE id=?", (rid,))
            source = json.loads(job["payload"])
            scan = c.sources.scan(
                **source,
                check=lambda: self.check(jid),
                progress=lambda p: self.progress(jid, {**result, **p}),
            )
            result.update(scan)
            if not wid:
                c.db.execute("UPDATE jobs SET state='READY' WHERE id=?", (jid,))
                self.progress(jid, result)
                return
            if c.model.state != "READY":
                raise RagError("MODEL_NOT_READY", "서버의 임베딩 모델을 준비하세요.", 503)
            revision = c.db.one("SELECT fingerprint,config FROM revisions WHERE id=?", (rid,))
            fingerprint, config = revision["fingerprint"], json.loads(revision["config"])
            # A queued/running build keeps the configuration selected when it was created.
            build_settings = c.s.model_copy(
                update={key: value for key, value in config.items() if key in type(c.s).model_fields}
            )
            manifest = {
                **result,
                "workspace_id": wid,
                "revision_id": rid,
                "documents": [],
                "chunks": 0,
                "reused_documents": 0,
                "embedded_chunks": 0,
                "stage": "BUILDING",
                "config": config,
                "review_accepted": bool(config.get("allow_review")),
                "timings_ms": {"parse": 0, "chunk": 0, "embedding": 0},
            }
            with c.workspaces.locks[wid]:
                self.check(jid)
                revpath = c.revisions.path(wid, rid)
                revpath.mkdir(parents=True, exist_ok=True)
                c.vectors.call("create", wid, rid, c.model.dimension)
                with open_database(revpath / "keyword.sqlite") as keyword:
                    keyword.execute("CREATE TABLE chunks(id TEXT PRIMARY KEY,payload TEXT)")
                    keyword.execute(
                        "CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,body,tokenize='unicode61')"
                    )
                c.db.execute("UPDATE revisions SET state='BUILDING' WHERE id=?", (rid,))
            read_bytes = 0
            for file in scan["files"]:
                self.check(jid)
                if file["state"] != "INCLUDED":
                    continue
                path = file["relative_path"]
                try:
                    data = c.sources.read(
                        source["root_id"], str(PurePosixPath(source["relative_path"]) / path)
                    )
                    read_bytes += len(data)
                    if read_bytes > c.s.max_total_bytes:
                        raise RagError(
                            "TOTAL_SIZE_LIMIT", "실제 읽은 자료가 전체 처리량 제한을 초과했습니다."
                        )
                    content_hash = hashlib.sha256(data).hexdigest()
                    with c.workspaces.locks[wid]:
                        self.check(jid)
                        doc = c.db.one(
                            "SELECT * FROM documents WHERE workspace_id=? AND relative_path=?", (wid, path)
                        )
                        if not doc:
                            doc = {"id": uid()}
                            c.db.execute("INSERT INTO documents VALUES(?,?,?)", (doc["id"], wid, path))
                        dv = c.db.one(
                            "SELECT * FROM document_versions WHERE workspace_id=? AND document_id=? AND content_hash=? AND fingerprint=?",
                            (wid, doc["id"], content_hash, fingerprint),
                        )
                    if dv:
                        parsed = json.loads(dv["parsed"])
                        chunks = json.loads(dv["chunks"])
                        manifest["reused_documents"] += 1
                    else:
                        t = time.monotonic()
                        parsed = (c.parser.parse(data, Path(path).suffix.lower(), True)
                                  if config.get("allow_review")
                                  else c.parser.parse(data, Path(path).suffix.lower()))
                        manifest["timings_ms"]["parse"] += round((time.monotonic() - t) * 1000)
                        t = time.monotonic()
                        chunks = chunk_document(parsed, path, c.model, build_settings)
                        manifest["timings_ms"]["chunk"] += round((time.monotonic() - t) * 1000)
                        if not chunks:
                            raise RagError("NO_SEARCHABLE_CONTENT")
                        if manifest["chunks"] + len(chunks) > c.s.max_chunks:
                            raise RagError("CHUNK_LIMIT")
                        t = time.monotonic()
                        for offset in range(0, len(chunks), 8):
                            self.check(jid)
                            batch = chunks[offset : offset + 8]
                            vectors = c.model.encode([x["search_text"] for x in batch])
                            for chunk, vector in zip(batch, vectors):
                                chunk["vector"] = vector
                        manifest["timings_ms"]["embedding"] += round((time.monotonic() - t) * 1000)
                        manifest["embedded_chunks"] += len(chunks)
                        dv = {"id": uid()}
                        with c.workspaces.locks[wid]:
                            self.check(jid)
                            snapshot = Path("workspaces") / wid / "snapshots" / (dv["id"] + ".bin")
                            (c.s.data_dir / snapshot).parent.mkdir(parents=True, exist_ok=True)
                            (c.s.data_dir / snapshot).write_bytes(data)
                            c.db.execute(
                                "INSERT INTO document_versions VALUES(?,?,?,?,?,?,?,?)",
                                (
                                    dv["id"],
                                    wid,
                                    doc["id"],
                                    content_hash,
                                    fingerprint,
                                    str(snapshot),
                                    dumps(parsed),
                                    dumps(chunks),
                                ),
                            )
                    if path.lower().endswith((".md", ".txt")):
                        # Build presentation once at ingestion, separate from search chunks.
                        c.evidence.ensure_view(wid, dv["id"], content_hash)
                    with c.workspaces.locks[wid]:
                        self.check(jid)
                        if manifest["chunks"] + len(chunks) > c.s.max_chunks:
                            raise RagError("CHUNK_LIMIT")
                        with open_database(revpath / "keyword.sqlite") as keyword:
                            for chunk in chunks:
                                evidence = {
                                    k: v for k, v in chunk.items() if k not in {"vector", "search_text"}
                                }
                                evidence.update(
                                    evidence_id=rid + "." + chunk["chunk_id"],
                                    workspace_id=wid,
                                    revision_id=rid,
                                    document_id=doc["id"],
                                    document_version_id=dv["id"],
                                    relative_path=path,
                                )
                                keyword.execute(
                                    "INSERT INTO chunks VALUES(?,?)", (chunk["chunk_id"], dumps(evidence))
                                )
                                keyword.execute(
                                    "INSERT INTO search VALUES(?,?)",
                                    (chunk["chunk_id"], keyword_text(chunk["search_text"])),
                                )
                        for offset in range(0, len(chunks), 64):
                            c.vectors.call("upsert", wid, rid, chunks[offset : offset + 64])
                    manifest["chunks"] += len(chunks)
                    manifest["documents"].append(
                        {
                            "document_id": doc["id"],
                            "document_version_id": dv["id"],
                            "relative_path": path,
                            "content_hash": content_hash,
                            "chunks": len(chunks),
                        }
                    )
                    reviews = [w for w in parsed.get("warnings", []) if isinstance(w, dict) and w.get("code")]
                    if reviews:
                        file.update(reason=reviews[0]["code"], warnings=reviews)
                    file.update(
                        state=("REVIEWED" if config.get("allow_review") else "PROCESSED_WITH_WARNINGS") if reviews else "PROCESSED", document_version_id=dv["id"], reused=bool(dv.get("chunks"))
                    )
                except RagError as error:
                    if error.code in {"CANCELLED", "NOT_FOUND", "SOURCE_ACCESS_REVOKED", "TOTAL_SIZE_LIMIT"}:
                        raise
                    file.update(state="FAILED", reason=error.code)
                self.progress(jid, manifest)
            self.check(jid)
            manifest["total_ms"] = round((time.monotonic() - started) * 1000)
            if any(f["state"] == "FAILED" for f in scan["files"]) and not config.get("allow_review"):
                manifest["stage"] = "PARTIAL"
                c.db.execute(
                    "UPDATE revisions SET state='PARTIAL',manifest=? WHERE id=?", (dumps(manifest), rid)
                )
                c.db.execute("UPDATE jobs SET state='PARTIAL' WHERE id=?", (jid,))
                self.progress(jid, manifest)
                return
            if not manifest["chunks"]:
                raise RagError("NO_SEARCHABLE_CONTENT", "색인할 내용이 없습니다. 기존 자료는 유지됩니다.")
            manifest["stage"] = "VALIDATING"
            c.db.execute("UPDATE revisions SET state='VALIDATING' WHERE id=?", (rid,))
            self.progress(jid, manifest)
            manifest["stage"] = "READY"
            c.revisions.activate(wid, rid, jid, manifest["chunks"], manifest)
        except Exception as error:
            code = error.code if isinstance(error, RagError) else "INDEX_FAILED"
            state = "CANCELLED" if code == "CANCELLED" else "FAILED"
            current = c.db.one("SELECT result FROM jobs WHERE id=?", (jid,))
            result = json.loads(current["result"] or "{}") if current else {}
            result.update(
                error_code=code,
                stage=state,
                message=error.message
                if isinstance(error, RagError)
                else "색인을 완료하지 못했습니다. 재시도하세요.",
            )
            with c.db.transaction():
                c.db.execute(
                    "UPDATE jobs SET state=?,result=?,updated_at=? WHERE id=? AND state!='READY'",
                    (state, dumps(result), time.time(), jid),
                )
                if rid:
                    c.db.execute("UPDATE revisions SET state=? WHERE id=? AND state!='READY'", (state, rid))

        finally:
            final = c.db.one("SELECT state FROM jobs WHERE id=?", (jid,))
            c.db.record("rag.job_finished", job_id=jid, workspace_id=wid, revision_id=rid,
                        state=final["state"] if final else "DELETED")

    def close(self):
        self.stop.set()
        self.heartbeat_thread.join(3)
        self.executor.shutdown(wait=True)
