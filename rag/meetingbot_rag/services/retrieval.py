"""Hybrid search and evidence restricted to a workspace revision."""

import json
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from ..db import open_database, uid
from ..markdown_views import VIEW_VERSION, read_page
from ..sources import RagError
from ..table_views import table_page


def keyword_text(text):
    words = re.findall(r"[\w]+", unicodedata.normalize("NFC", text).lower())
    grams = [word[i : i + 2] for word in words if re.search("[가-힣]", word) for i in range(len(word) - 1)]
    return " ".join(words + grams)


def subject_match(name, query):
    """Prefer an explicitly named source, accepting tense-consonant spelling variants.

    Exact spellings always score higher; original source text and citations stay intact.
    """
    def compact(text):
        return re.sub(r"[\W_]", "", unicodedata.normalize("NFC", text).lower())
    name, query = compact(name), compact(query)
    if len(name) < 2:
        return 0
    if name in query:
        return 2
    def loose(text):
        return unicodedata.normalize("NFD", text).translate(str.maketrans("ᄁᄄᄈᄊᄍ", "ᄀᄃᄇᄉᄌ"))
    return 1 if len(name) >= 3 and loose(name) in loose(query) else 0


class RetrievalService:
    def __init__(self, core):
        self.c = core
        # Admission reservations, not duplicated models or preemptible computation.
        # LocalEmbedding and VectorAdapter retain their own serialized ownership.
        self.gate = threading.BoundedSemaphore(1)
        self.priority_gate = threading.BoundedSemaphore(1)
        self.lane = threading.local()

    @contextmanager
    def priority_lane(self):
        """Use the reserved PQ admission slot only on the current worker thread."""
        previous = getattr(self.lane, "priority", False)
        self.lane.priority = True
        try:
            yield
        finally:
            self.lane.priority = previous

    def search(self, wid, query, revision_id=None, top_k=None):
        gate = self.priority_gate if getattr(self.lane, "priority", False) else self.gate
        if not gate.acquire(blocking=False):
            raise RagError("SEARCH_BUSY", "다른 검색을 처리하고 있습니다. 잠시 후 다시 시도하세요.", 429)
        try:
            return self._search(wid, query, revision_id, top_k)
        finally:
            gate.release()

    @staticmethod
    def _revision_snapshot(revision):
        return {key: revision.get(key) for key in ("id", "fingerprint", "config", "manifest")}

    def _validate_snapshot(self, wid, rid, revision_snapshot, policy_version):
        # Re-resolving also validates deletion and the workspace's current source access.
        with self.c.workspaces.locks[wid]:
            _, current = self.c.revisions.resolve(wid, rid)
            if self._revision_snapshot(current) != revision_snapshot:
                raise RagError("REVISION_CHANGED", "검색 중 자료 버전이 변경되었습니다.", 409)
            _, current_policy = self.c.sources.roots()
            if current_policy != policy_version:
                raise RagError("SOURCE_POLICY_CHANGED", "검색 중 자료 접근 범위가 변경되었습니다.", 409)

    def _search(self, wid, query, revision_id=None, top_k=None):
        c = self.c
        settings, settings_version = c.runtime_settings.snapshot()
        result_limit = min(top_k, settings.top_k) if top_k is not None else settings.top_k
        started = time.monotonic()
        with c.workspaces.locks[wid]:
            ws, rev = c.revisions.resolve(wid, revision_id)
            saved_config = json.loads(rev["config"])
            if any(saved_config.get(k) != getattr(c.s, k) for k in ("embedding_model", "embedding_revision")):
                raise RagError(
                    "MODEL_REVISION_MISMATCH",
                    "이 자료 버전과 임베딩 모델이 다릅니다. 자료를 다시 준비하세요.",
                    409,
                )
            rid = rev["id"]
            revision_snapshot = self._revision_snapshot(rev)
            _, policy_version = c.sources.roots()
            keyword_path = c.revisions.path(wid, rid) / "keyword.sqlite"
        # A shared/SQ query cannot retain a workspace lock while encoding or waiting
        # for the Qdrant owner. Both adapters enforce their existing thread safety.
        try:
            vector = c.model.encode([query], query=True)[0]
            embedding_ms = round((time.monotonic() - started) * 1000)
            candidates = c.vectors.call("search", wid, rid, vector)
            terms = list(dict.fromkeys(keyword_text(query).split()))[:80]
            match = " OR ".join('"' + x.replace('"', '""') + '"' for x in terms)
            scores, evidence = defaultdict(float), {}
            keyword_ids = []
            # Read-only mode cannot recreate an empty database if a revision was deleted.
            with open_database(keyword_path, readonly=True) as keyword:
                if match:
                    keyword_ids = [
                        r[0]
                        for r in keyword.execute(
                            "SELECT id FROM search WHERE search MATCH ? ORDER BY bm25(search) LIMIT ?",
                            (match, c.s.candidates),
                        )
                    ]
                allowed = {cid for cid, score in candidates if score >= c.s.min_vector_score} | set(
                    keyword_ids
                )
                for ranking in ([cid for cid, _ in candidates], keyword_ids):
                    for rank, cid in enumerate(ranking, 1):
                        if cid in allowed:
                            scores[cid] += 1 / (60 + rank)
                # Specific document names must outrank generic index/readme hits.
                # Filesystem paths on macOS may use decomposed Hangul.
                for document in json.loads(rev["manifest"]).get("documents", []):
                    strength = subject_match(Path(document["relative_path"]).stem, query)
                    if strength:
                        rows = keyword.execute(
                            "SELECT id FROM chunks WHERE json_extract(payload, '$.relative_path')=? ORDER BY rowid",
                            (document["relative_path"],),
                        ).fetchall()
                        ids = [row[0] for row in rows]
                        matched = [cid for cid in ids if cid in scores]
                        # Preserve relevant late sections instead of replacing them
                        # with the first few chunks of a specifically named file.
                        for cid in matched or ids[:result_limit]:
                            scores[cid] += 0.1 * strength
                for cid in sorted(scores, key=scores.get, reverse=True)[:result_limit]:
                    row = keyword.execute("SELECT payload FROM chunks WHERE id=?", (cid,)).fetchone()
                    if row:
                        evidence[cid] = json.loads(row[0])
        except Exception:
            # A concurrent removal may make an adapter or SQLite fail first. Prefer
            # the current access/revision error and never return captured excerpts.
            self._validate_snapshot(wid, rid, revision_snapshot, policy_version)
            raise
        self._validate_snapshot(wid, rid, revision_snapshot, policy_version)
        return {
            "request_id": uid(),
            "workspace_id": wid,
            "knowledge_base_id": ws["knowledge_base_id"],
            "revision_id": rid,
            "retrieval_settings_version": settings_version,
            "access_scope_version": policy_version,
            "query": query,
            "evidence": list(evidence.values()),
            "status": "found" if evidence else "insufficient_evidence",
            "timings_ms": {
                "query_embedding": embedding_ms,
                "retrieval": round((time.monotonic() - started) * 1000) - embedding_ms,
            },
            "ranking": "RRF (순위 점수는 정답 확률이 아닙니다)",
        }

    def answer_context(self, result, max_chars):
        """Expand matching documents/sheets with actual citable chunks, within budget.

        A section hit is enough to find the source, but not to answer a question
        about a whole recipe or catalogue. Keep original evidence IDs and locations.
        """
        c = self.c
        wid, rid = result["workspace_id"], result["revision_id"]
        groups = {}
        for rank, item in enumerate(result["evidence"]):
            key = (item["document_id"], item["location"].get("sheet"))
            group = groups.setdefault(key, {"score": 0, "subject": 0})
            group["score"] += 1 / (60 + rank)
            name = key[1] or Path(item["relative_path"]).stem
            group["subject"] = subject_match(name, result["query"])
            group["score"] += group["subject"]
        if any(group["subject"] for group in groups.values()):
            best = max(group["subject"] for group in groups.values())
            groups = {key: group for key, group in groups.items() if group["subject"] == best}
        chosen, seen, used = [], set(), 0

        def include(item):
            nonlocal used
            if item["evidence_id"] in seen:
                return
            cost = len(json.dumps({k: item.get(k) for k in ("evidence_id", "relative_path", "title_path", "text")}, ensure_ascii=False))
            if used + cost > max_chars or len(chosen) >= 64:
                return
            seen.add(item["evidence_id"])
            chosen.append(item)
            used += cost

        # Never lose the matched passage while adding earlier sections of a long file.
        for item in result["evidence"]:
            if (item["document_id"], item["location"].get("sheet")) in groups:
                include(item)
        with c.workspaces.locks[wid]:
            c.revisions.resolve(wid, rid)
            _, policy = c.sources.roots()
            if result.get("access_scope_version") != policy:
                raise RagError("SOURCE_POLICY_CHANGED", "자료 접근 범위가 변경되었습니다.", 409)
            with open_database(c.revisions.path(wid, rid) / "keyword.sqlite", readonly=True) as db:
                for (document, sheet), group in sorted(groups.items(), key=lambda pair: -pair[1]["score"]):
                    rows = db.execute(
                        "SELECT payload FROM chunks WHERE json_extract(payload, '$.document_id')=? "
                        "AND (? IS NULL OR json_extract(payload, '$.location.sheet')=?) ORDER BY rowid",
                        (document, sheet, sheet),
                    )
                    for (raw,) in rows:
                        include(json.loads(raw))
        return chosen or result["evidence"]


class EvidenceService:
    build_gate = threading.BoundedSemaphore(1)

    def __init__(self, core):
        self.c = core

    def readable_revision(self, wid, revision_id=None):
        ws = self.c.workspaces.get(wid)
        rid = revision_id or ws["active_revision_id"]
        rev = self.c.db.one("SELECT * FROM revisions WHERE workspace_id=? AND id=? AND state IN ('READY','PARTIAL')", (wid, rid))
        if not rev:
            raise RagError("REVISION_NOT_READY", "열람할 자료 버전이 없습니다.", 409)
        return ws, rev

    def document(self, wid, relative_path, revision_id=None, metadata_only=False):
        """Open only documents already present in the requested accessible revision."""
        c = self.c
        with c.workspaces.locks[wid]:
            _, rev = self.readable_revision(wid, revision_id)
            matches = [
                doc["relative_path"]
                for doc in json.loads(rev["manifest"]).get("documents", [])
                if unicodedata.normalize("NFC", doc["relative_path"])
                == unicodedata.normalize("NFC", relative_path)
            ]
            if len(matches) != 1:
                raise RagError("NOT_FOUND", "이 워크스페이스에서 문서를 찾을 수 없습니다.", 404)
            with open_database(c.revisions.path(wid, rev["id"]) / "keyword.sqlite") as keyword:
                row = keyword.execute(
                    "SELECT payload FROM chunks WHERE json_extract(payload, '$.relative_path')=? ORDER BY rowid LIMIT 1",
                    (matches[0],),
                ).fetchone()
            if not row:
                raise RagError("NOT_FOUND", "열람할 수 있는 문서 내용이 없습니다.", 404)
            evidence = json.loads(row[0])
            if metadata_only:
                return {"workspace_id": wid, "revision_id": rev["id"], "evidence": evidence}
            return self.get(wid, evidence["evidence_id"], rev["id"])

    def source_preview(self, wid, relative_path, sheet=None, page=None, source_offset=None):
        c = self.c
        ws = c.workspaces.get(wid)
        source = ws["source"]
        if not source:
            raise RagError("SOURCE_REQUIRED")
        # read() enforces source containment, extensions, symlinks and byte limits.
        if relative_path.startswith("/") or ".." in PurePosixPath(relative_path).parts:
            raise RagError("INVALID_PATH", status=403)
        data = c.sources.read(source["root_id"], str(PurePosixPath(source["relative_path"]) / relative_path))
        parsed = c.parser.parse(data, Path(relative_path).suffix.lower(), True)
        if parsed["kind"] == "table":
            document = table_page(parsed, {}, sheet, page)
        else:
            text = parsed["text"]
            offset = min(source_offset or 0, len(text))
            part = text[offset:offset + 3000]
            document = {"kind": "source_page", "text": part, "start_line": text[:offset].count("\n") + 1,
                        "offset": offset, "next_offset": offset + len(part) if offset + len(part) < len(text) else None,
                        "total_lines": text.count("\n") + 1, "total_bytes": len(text.encode()),
                        "mid_line": offset > 0 and text[offset - 1] != "\n"}
        c.workspaces.get(wid)
        return {"workspace_id": wid, "revision_id": "source", "document": document}

    def ensure_view(self, wid, version_id, content_hash):
        """No registry parsed/chunks blob read on cache hits. One cold builder globally."""
        path = self.c.s.data_dir / "workspaces" / wid / "snapshots" / f"{version_id}.view.sqlite"
        if path.exists():
            try:
                with open_database(path, readonly=True) as db:
                    meta = db.execute("SELECT version,content_hash FROM meta").fetchone()
                if meta == (VIEW_VERSION, content_hash):
                    return path
            except sqlite3.Error:
                pass
        if not self.build_gate.acquire(timeout=2):
            raise RagError("VIEW_BUSY", "문서를 준비하고 있습니다. 잠시 후 다시 시도해 주세요.", 503)
        temporary = path.with_name(path.name + ".building")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.unlink(missing_ok=True)
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "meetingbot_rag.markdown_views",
                    str(self.c.s.data_dir / "registry.sqlite"),
                    version_id,
                    str(temporary),
                ],
                cwd=Path(__file__).resolve().parents[2],
                capture_output=True,
                timeout=60,
            )
            if process.returncode:
                raise RagError(
                    "VIEW_BUILD_FAILED", "문서 표시를 준비하지 못했습니다. 다시 시도해 주세요.", 503
                )
            temporary.chmod(0o600)
            temporary.replace(path)
            return path
        except subprocess.TimeoutExpired:
            raise RagError(
                "VIEW_BUILD_TIMEOUT", "문서 준비 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", 503
            ) from None
        finally:
            temporary.unlink(missing_ok=True)
            self.build_gate.release()

    def get(
        self,
        wid,
        eid,
        revision_id,
        *,
        view=None,
        page=None,
        anchor=None,
        outline_offset=0,
        source_offset=None,
        sheet=None,
    ):
        c = self.c
        with c.workspaces.locks[wid]:
            _, rev = self.readable_revision(wid, revision_id)
            if not re.fullmatch(r"[a-f0-9]{32}\.[a-f0-9]{32}", eid) or eid.split(".")[0] != rev["id"]:
                raise RagError("NOT_FOUND", "근거를 찾을 수 없습니다.", 404)
            with open_database(c.revisions.path(wid, rev["id"]) / "keyword.sqlite") as keyword:
                row = keyword.execute(
                    "SELECT payload FROM chunks WHERE id=?", (eid.split(".")[1],)
                ).fetchone()
            if not row:
                raise RagError("NOT_FOUND", "근거를 찾을 수 없습니다.", 404)
            evidence = json.loads(row[0])
            if view and evidence["relative_path"].lower().endswith((".md", ".txt")):
                dv = c.db.one(
                    "SELECT content_hash FROM document_versions WHERE id=? AND workspace_id=?",
                    (evidence["document_version_id"], wid),
                )
                path = self.ensure_view(wid, evidence["document_version_id"], dv["content_hash"])
                rendered = read_page(
                    path,
                    evidence,
                    mode=view,
                    page=page,
                    anchor=anchor,
                    outline_offset=outline_offset,
                    source_offset=source_offset,
                )
                return {
                    "workspace_id": wid,
                    "revision_id": rev["id"],
                    "request_id": uid(),
                    "content_hash": dv["content_hash"],
                    "document": rendered,
                }
            if view:
                dv = c.db.one("SELECT parsed,snapshot FROM document_versions WHERE id=? AND workspace_id=?",
                              (evidence["document_version_id"], wid))
                parsed = json.loads(dv["parsed"])
                if not parsed.get("sheets"):
                    parsed = c.parser.parse((c.s.data_dir / dv["snapshot"]).read_bytes(),
                                            Path(evidence["relative_path"]).suffix.lower(), True)
                return {"workspace_id": wid, "revision_id": rev["id"],
                        "document": table_page(parsed, evidence, sheet, page)}
            dv = c.db.one(
                "SELECT parsed,content_hash FROM document_versions WHERE id=? AND workspace_id=?",
                (evidence["document_version_id"], wid),
            )
            return {
                "workspace_id": wid,
                "revision_id": rev["id"],
                "request_id": uid(),
                "evidence": evidence,
                "snapshot": json.loads(dv["parsed"]),
                "content_hash": dv["content_hash"],
                "source": "revision_snapshot",
            }
