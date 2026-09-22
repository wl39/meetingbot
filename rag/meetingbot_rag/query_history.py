"""Account-owned query records; browser IDs never grant access to another account."""

import json
import time

from .db import dumps, uid
from .sources import RagError
from .workspace_access import visible


class QueryHistory:
    def __init__(self, core, access):
        self.c, self.access = core, access

    @property
    def retention_days(self):
        return min(1, self.c.s.history_days) if self.c.s.demo_mode else self.c.s.history_days

    def create(self, wid, body, principal, kind, *, queued=False, idempotency_key=None):
        c = self.c
        account = self.access.profile(principal)
        created = time.time()
        result = {
            "request_id": uid(),
            "workspace_id": wid,
            "revision_id": body.revision_id,
            "query": body.query,
            "status": "queued" if queued else "processing",
            "answer": "",
            "evidence": [],
            "citations": [],
            "timings_ms": {},
            "created_at": created,
            "kind": kind,
        }
        rid = result["request_id"]
        with c.workspaces.locks[wid], c.db.transaction():
            ws = c.workspaces.get(wid)
            if idempotency_key:
                existing = c.db.one(
                    "SELECT * FROM query_runs WHERE subject=? AND workspace_id=? AND idempotency_key=?",
                    (principal.subject, wid, idempotency_key),
                )
                if existing:
                    if json.loads(existing["input"])["request"] != body.model_dump():
                        raise RagError("IDEMPOTENCY_CONFLICT", "이미 다른 질문에 사용한 요청 ID입니다.", 409)
                    return json.loads(existing["result"])
            payload = None
            if queued:
                resolved = body.model_dump()
                resolved["revision_id"] = body.revision_id or ws["active_revision_id"]
                result["revision_id"] = resolved["revision_id"]
                payload = dumps({"request": body.model_dump(), "resolved": resolved})
            c.db.execute(
                "DELETE FROM query_runs WHERE created_at<? "
                "AND json_extract(result,'$.status') NOT IN ('queued','processing')",
                (created - self.retention_days * 86400,)
            )
            c.db.execute(
                "INSERT INTO query_runs(id,workspace_id,revision_id,created_at,result,subject,account_label,"
                "account_role,kind,workspace_name,input,idempotency_key) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid,
                    wid,
                    result["revision_id"],
                    created,
                    dumps(result),
                    principal.subject,
                    account["label"],
                    principal.role,
                    kind,
                    ws["name"],
                    payload,
                    idempotency_key,
                ),
            )
        return result

    def run(self, wid, body, principal, kind, compute):
        result = self.create(wid, body, principal, kind)
        rid, created = result["request_id"], result["created_at"]
        try:
            result = {**compute(), "request_id": rid, "created_at": created, "kind": kind}
            return result
        except Exception as error:
            result.update(
                status="failed",
                reason=error.code if isinstance(error, RagError) else "REQUEST_FAILED",
                answer=error.message
                if isinstance(error, RagError)
                else "요청을 완료하지 못했습니다. 다시 시도해 주세요.",
            )
            raise
        finally:
            # A concurrently deleted workspace must not be recreated by a late answer.
            with self.c.workspaces.locks[wid]:
                self.c.db.execute(
                    "UPDATE query_runs SET revision_id=?,result=? WHERE id=?",
                    (result.get("revision_id"), dumps(result), rid),
                )

    def conditions(
        self, principal, scope, *, q="", subject=None, workspace_id=None, kind=None, since=None, until=None
    ):
        if scope == "all" and not principal.manages_data:
            raise RagError("FORBIDDEN", "전체 질문 기록은 관리자만 확인할 수 있습니다.", 403)
        clauses, args = ["(created_at>=? OR json_extract(result,'$.status') IN ('queued','processing'))"], [
            time.time() - self.retention_days * 86400
        ]
        # History contains document excerpts, so source revocation also applies here.
        available = []
        candidates = self.c.db.all(
            "SELECT w.id,s.root_id,s.relative_path,s.policy FROM workspaces w "
            "LEFT JOIN sources s ON s.workspace_id=w.id WHERE w.deleted=0"
            + (" AND w.id=?" if workspace_id else ""),
            (workspace_id,) if workspace_id else (),
        )
        for workspace in candidates:
            if not visible(self.c, principal, workspace["id"]):
                continue
            try:
                if workspace["root_id"]:
                    self.c.sources.validate_source(workspace)
            except RagError:
                continue
            available.append(workspace["id"])
        clauses.append("workspace_id IN (SELECT value FROM json_each(?))")
        args.append(dumps(available))
        if scope != "all":
            clauses.append("subject=?")
            args.append(principal.subject)
        elif subject:
            clauses.append("subject IS NULL" if subject == "legacy" else "subject=?")
            if subject != "legacy":
                args.append(subject)
        for column, value in (("workspace_id", workspace_id), ("kind", kind)):
            if value:
                clauses.append(f"{column}=?")
                args.append(value)
        if q.strip():
            clauses.append(
                "(instr(lower(COALESCE(json_extract(result,'$.query'),'')),lower(?))>0 OR "
                "instr(lower(COALESCE(json_extract(result,'$.answer'),'')),lower(?))>0)"
            )
            args.extend([q.strip(), q.strip()])
        for operator, value in ((">=", since), ("<", until)):
            if value is not None:
                clauses.append(f"created_at{operator}?")
                args.append(value)
        return " AND ".join(clauses), args

    def list(self, principal, scope="mine", limit=25, offset=0, **filters):
        where, args = self.conditions(principal, scope, **filters)
        with self.c.db.lock:
            total = self.c.db.one(f"SELECT COUNT(*) n FROM query_runs WHERE {where}", args)["n"]
            items = self.c.db.all(
                "SELECT id,workspace_id,workspace_name,created_at,subject,account_label,account_role,kind,"
                "json_extract(result,'$.query') query,json_extract(result,'$.status') status,"
                "substr(COALESCE(json_extract(result,'$.answer'),''),1,240) answer_preview "
                f"FROM query_runs WHERE {where} ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                (*args, limit, offset),
            )
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "retention_days": self.retention_days,
        }

    def filters(self, principal, scope="mine"):
        where, args = self.conditions(principal, scope)
        accounts = (
            self.c.db.all(
                "SELECT subject,MAX(account_label) label,MAX(account_role) role,COUNT(*) count "
                f"FROM query_runs WHERE {where} GROUP BY subject ORDER BY MAX(created_at) DESC",
                args,
            )
            if scope == "all"
            else []
        )
        workspaces = self.c.db.all(
            f"SELECT workspace_id id,MAX(workspace_name) name FROM query_runs WHERE {where} "
            "GROUP BY workspace_id ORDER BY name",
            args,
        )
        return {"accounts": accounts, "workspaces": workspaces}

    def get(self, principal, record_id, scope="mine"):
        where, args = self.conditions(principal, scope)
        row = self.c.db.one(f"SELECT * FROM query_runs WHERE id=? AND {where}", (record_id, *args))
        if not row or not visible(self.c, principal, row["workspace_id"]):
            raise RagError("NOT_FOUND", "질문 기록을 찾을 수 없거나 접근 권한이 없습니다.", 404)
        for internal in ("input", "idempotency_key", "available_at"):
            row.pop(internal, None)
        return {
            **row,
            "result": {**json.loads(row["result"]), "created_at": row["created_at"], "kind": row["kind"]},
        }

    def recent(self, principal, wid):
        where, args = self.conditions(principal, "mine", workspace_id=wid)
        return [
            {**json.loads(row["result"]), "created_at": row["created_at"], "kind": row["kind"]}
            for row in self.c.db.all(
                f"SELECT result,created_at,kind FROM query_runs WHERE {where} "
                "ORDER BY created_at DESC,id DESC LIMIT 100",
                args,
            )
        ]
