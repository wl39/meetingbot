"""Durable two-queue meeting processing with independent classification and deadlines.

One process owns the database (the application's existing process lock). Claims are
fenced so superseded/cancelled work cannot publish after an external call returns.
The dedicated live PQ lane never executes file or SQ work.
"""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .db import dumps, uid
from .meeting import Extraction, MeetingInput, MeetingUtterance
from .meeting_policy import MeetingPolicies
from .sources import RagError

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "SUPERSEDED"}
RUNNABLE = {"QUEUED", "PAUSED", "RETRY_WAIT", "AWAITING_CONTEXT"}
# Independent classifier lanes also share the global three-request LLM cap.
FILTER_SLOTS = ("filter", "filter-2")
TRANSIENT = {
    "LLM_BUSY",
    "SEARCH_BUSY",
    "PROXY_RATE_LIMIT",
    "PROXY_UNAVAILABLE",
    "LLM_UNAVAILABLE",
    "LLM_REQUEST_FAILED",
    "MEETING_TIMEOUT",
    "PROXY_TIMEOUT",
    "INVALID_MEETING_LLM_OUTPUT",
}


class JobInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str = Field(min_length=1, max_length=128)
    utterance: MeetingUtterance
    context: list[dict] = Field(default_factory=list, max_length=3)
    following_context: list[dict] = Field(default_factory=list, max_length=2)
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    origin: Literal["live", "file"] = "live"
    source_key: str = Field(min_length=1, max_length=128)
    received_at: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    addressed_to_ai: bool = False
    source_generation: int = Field(default=0, ge=0)


def meeting_body(data):
    return MeetingInput.model_validate(
        {
            "session_id": data["session_id"],
            "utterance": data["utterance"],
            "revision_id": data.get("revision_id"),
            "context": [
                {"text": x["text"], "speaker_id": x.get("speaker_id")}
                for x in data.get("context", [])
                if x.get("text", "").strip()
            ],
        }
    )


def extracted(classification):
    return Extraction(
        relevant=True,
        keywords=classification["keywords"],
        query=classification["query"],
        intent=classification["intent"],
        claim=classification["claim"],
    )


class MeetingJobs:
    def __init__(self, core, answer, meeting, access, classifier=None, clock=time.time):
        from .meeting_classifier import MeetingClassifier

        self.c, self.answer, self.meeting, self.access = core, answer, meeting, access
        self.classifier = classifier or MeetingClassifier(core, answer)
        self.policies = MeetingPolicies(core)
        self.clock = clock
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=len(FILTER_SLOTS) + 2, thread_name_prefix="meeting")
        self.running = {}
        self.modes = {}
        self.recovery_since = {}
        self.usage = {"filter": {}, "priority": {}, "shared": {}}
        self.usage_lock = threading.Lock()
        self.thread = None
        # Process lock excludes old workers; persisted checkpoints survive restart.
        core.db.execute(
            "UPDATE meeting_jobs SET state='QUEUED',lease_token=NULL,updated_at=? "
            "WHERE state IN ('RUNNING','CLASSIFYING','PAUSED')",
            (self.clock(),),
        )

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="meeting-scheduler", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=2)
        self.pool.shutdown(wait=True, cancel_futures=True)

    def subscription(self, wid, sid, principal, enabled, revision_id):
        self._session_access(sid, principal)
        self.c.workspaces.get(wid)
        if enabled:
            self.meeting.approved_config(wid)
            _, rev = self.c.revisions.resolve(wid, revision_id)
            revision_id = rev["id"]
        with self.c.db.transaction():
            existing = self.c.db.one(
                "SELECT * FROM meeting_subscriptions WHERE workspace_id=? AND session_id=?",
                (wid, sid),
            )
            owner = existing["owner"] if existing else principal.subject
            version = existing["version"] + 1 if existing else 1
            self.c.db.execute(
                "INSERT INTO meeting_subscriptions(workspace_id,session_id,owner,enabled,revision_id,version,"
                "updated_at) VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(workspace_id,session_id) DO UPDATE SET enabled=excluded.enabled,"
                "revision_id=excluded.revision_id,version=excluded.version,updated_at=excluded.updated_at",
                (wid, sid, owner, int(enabled), revision_id, version, self.clock()),
            )
            if not enabled or (existing and existing["revision_id"] != revision_id):
                self._invalidate(wid, sid, "CANCELLED" if not enabled else "SUPERSEDED")
        self.wake.set()
        return {"enabled": enabled, "workspace_id": wid, "revision_id": revision_id, "version": version}

    def _session_access(self, sid, principal):
        if self.access.owner(sid) != principal.subject:
            raise RagError("SESSION_NOT_FOUND", status=404)

    def _grant(self, wid, sid, principal, internal=False, allow_disabled=False):
        row = self.c.db.one(
            "SELECT * FROM meeting_subscriptions WHERE workspace_id=? AND session_id=?",
            (wid, sid),
        )
        if internal:
            if principal.role != "superadmin" or principal.subject != "superadmin":
                raise RagError("ROLE_DENIED", status=403)
        else:
            self._session_access(sid, principal)
        if not row or (not allow_disabled and not row["enabled"]):
            raise RagError("MEETING_SUBSCRIPTION_REQUIRED", status=409)
        if not internal and row["owner"] != principal.subject:
            raise RagError("SESSION_NOT_FOUND", status=404)
        return row

    def _owner_valid(self, subject):
        if subject == "superadmin":
            return True
        with self.access.db() as db:
            if subject.startswith("guest_"):
                return bool(
                    db.execute(
                        "SELECT 1 FROM access_sessions WHERE subject=? AND expires>?",
                        (subject, self.clock()),
                    ).fetchone()
                )
            return bool(
                db.execute(
                    "SELECT 1 FROM access_keys WHERE id=? AND revoked IS NULL",
                    (subject,),
                ).fetchone()
            )

    def enqueue(self, wid, body, principal, internal=False):
        grant = self._grant(wid, body.session_id, principal, internal)
        if not self._owner_valid(grant["owner"]):
            raise RagError("AUTH_REQUIRED", status=401)
        self.meeting.approved_config(wid)
        _, rev = self.c.revisions.resolve(wid, body.revision_id or grant["revision_id"])
        if grant["revision_id"] != rev["id"]:
            raise RagError("STALE_SUBSCRIPTION", status=409)
        if internal and body.source_generation < grant["source_generation"]:
            raise RagError("STALE_UTTERANCE", status=409)
        policy = self.policies.get(wid)
        data = body.model_dump()
        data["revision_id"] = rev["id"]
        # Validate every context before any LLM transmission, never trust caller role claims.
        for part in data["context"] + data["following_context"]:
            if not isinstance(part.get("text"), str) or len(part["text"]) > 10000:
                raise RagError("INVALID_MEETING_INPUT", status=422)
        meeting_body(data)
        now = self.clock()
        received = min(body.received_at or now, now) if internal else now
        with self.c.db.transaction():
            old = self.c.db.one(
                "SELECT * FROM meeting_jobs WHERE workspace_id=? AND session_id=? AND source_key=? "
                "AND policy_version=?",
                (wid, body.session_id, body.source_key, policy["version"]),
            )
            if old and old["state"] not in {"CANCELLED", "SUPERSEDED"}:
                return self.public(old)
            if old and old["state"] == "SUPERSEDED":
                raise RagError("STALE_UTTERANCE", status=409)
            latest = self.c.db.one(
                "SELECT utterance_revision,input FROM meeting_jobs WHERE workspace_id=? AND session_id=? "
                "AND utterance_id=? AND state NOT IN ('CANCELLED','SUPERSEDED') ORDER BY created_at DESC LIMIT 1",
                (wid, body.session_id, body.utterance.utterance_id),
            )
            if latest and (
                latest["utterance_revision"] > body.utterance.revision
                or json.loads(latest["input"]).get("source_generation", 0) > body.source_generation
            ):
                raise RagError("STALE_UTTERANCE", status=409)
            count = self.c.db.one(
                "SELECT COUNT(*) n FROM meeting_jobs WHERE workspace_id=? "
                "AND state NOT IN ('COMPLETED','FAILED','CANCELLED','SUPERSEDED')",
                (wid,),
            )["n"]
            global_count = self.c.db.one(
                "SELECT COUNT(*) n FROM meeting_jobs WHERE state NOT IN "
                "('COMPLETED','FAILED','CANCELLED','SUPERSEDED')",
            )["n"]
            if count >= (4 if body.origin == "file" else 32) or global_count >= 128:
                raise RagError("MEETING_CAPACITY", "분석 작업을 보관 중입니다. 잠시 후 접수합니다.", 429)
            if self.c.s.demo_mode and not self.access.consume(grant["owner"], "ai", 20, 300):
                raise RagError("DEMO_DAILY_LIMIT", status=429)
            self.c.db.execute(
                "UPDATE meeting_jobs SET state='SUPERSEDED',result=NULL,checkpoint=NULL,lease_token=NULL,"
                "updated_at=? WHERE workspace_id=? AND session_id=? AND utterance_id=? "
                "AND state NOT IN ('SUPERSEDED','CANCELLED')",
                (now, wid, body.session_id, body.utterance.utterance_id),
            )
            if old:
                self.c.db.execute("DELETE FROM meeting_jobs WHERE id=?", (old["id"],))
            jid = uid()
            values = {
                "id": jid,
                "workspace_id": wid,
                "session_id": body.session_id,
                "owner": grant["owner"],
                "utterance_id": body.utterance.utterance_id,
                "utterance_revision": body.utterance.revision,
                "source_key": body.source_key,
                "text": body.utterance.text,
                "input": dumps(data),
                "origin": body.origin,
                "state": "QUEUED",
                "stage": "classify",
                "received_at": received,
                "deadline_at": received + policy["priority_response_target_seconds"],
                "policy_version": policy["version"],
                "policy": dumps(policy),
                "provider_id": self.answer.settings.provider_id(self.answer.settings.snapshot()[0]),
                "created_at": now,
                "updated_at": now,
                "available_at": now,
            }
            columns = ",".join(values)
            placeholders = ",".join("?" for _ in values)
            self.c.db.execute(
                f"INSERT INTO meeting_jobs({columns}) VALUES({placeholders})", tuple(values.values())
            )
        self.wake.set()
        return self.public(self.c.db.one("SELECT * FROM meeting_jobs WHERE id=?", (jid,)))

    def _invalidate(self, wid, sid, state):
        # Stopping a subscription cancels unfinished work, while completed
        # classifications and answers remain available in the session archive.
        terminal_filter = " AND state NOT IN ('COMPLETED','FAILED')" if state == "CANCELLED" else ""
        self.c.db.execute(
            "UPDATE meeting_jobs SET state=?,lease_token=NULL,result=NULL,checkpoint=NULL,updated_at=? "
            "WHERE workspace_id=? AND session_id=? AND state NOT IN ('CANCELLED','SUPERSEDED')"
            + terminal_filter,
            (state, self.clock(), wid, sid),
        )

    def cancel(self, wid, sid, principal, internal=False, delete=False):
        # Workspace deletion already cascades to its jobs and subscriptions.
        # Let the authenticated bridge finish its durable cleanup receipt.
        if internal and principal.role == "superadmin" and not self.c.db.one(
            "SELECT id FROM workspaces WHERE id=?", (wid,)
        ):
            return {"cancelled": True, "deleted": delete}
        self._grant(wid, sid, principal, internal, allow_disabled=True)
        with self.c.db.transaction():
            self._invalidate(wid, sid, "CANCELLED")
            self.c.db.execute(
                "UPDATE meeting_subscriptions SET enabled=0,version=version+1 WHERE workspace_id=? AND session_id=?",
                (wid, sid),
            )
            if delete:
                self.c.db.execute(
                    "DELETE FROM meeting_jobs WHERE workspace_id=? AND session_id=?", (wid, sid)
                )
        return {"cancelled": True, "deleted": delete}

    def sync(self, wid, sid, utterance_ids, principal, internal=False, generation=0):
        grant = self._grant(wid, sid, principal, internal, allow_disabled=True)
        present = set(utterance_ids)
        with self.c.db.transaction():
            grant = self.c.db.one(
                "SELECT * FROM meeting_subscriptions WHERE workspace_id=? AND session_id=?",
                (wid, sid),
            )
            if generation < grant["source_generation"]:
                raise RagError("STALE_SNAPSHOT", status=409)
            self.c.db.execute(
                "UPDATE meeting_subscriptions SET source_generation=? WHERE workspace_id=? AND session_id=?",
                (generation, wid, sid),
            )
            for row in self.c.db.all(
                "SELECT id,utterance_id FROM meeting_jobs WHERE workspace_id=? AND session_id=? "
                "AND state NOT IN ('CANCELLED','SUPERSEDED')",
                (wid, sid),
            ):
                if row["utterance_id"] not in present:
                    self.c.db.execute(
                        "UPDATE meeting_jobs SET state='SUPERSEDED',lease_token=NULL,result=NULL,checkpoint=NULL,"
                        "updated_at=? WHERE id=?",
                        (self.clock(), row["id"]),
                    )
        return {"synced": True}

    def retry(self, wid, sid, jid, principal):
        self._grant(wid, sid, principal)
        row = self.c.db.one(
            "SELECT * FROM meeting_jobs WHERE id=? AND workspace_id=? AND session_id=?", (jid, wid, sid)
        )
        if not row:
            raise RagError("NOT_FOUND", status=404)
        if row["state"] == "FAILED":
            self.meeting.approved_config(wid)
            policy = self.policies.get(wid)
            config, _ = self.answer.settings.snapshot()
            self.c.db.execute(
                "UPDATE meeting_jobs SET state='QUEUED',stage='classify',score=NULL,classification=NULL,"
                "queue_class=NULL,checkpoint=NULL,result=NULL,lease_token=NULL,attempts=0,reason=NULL,"
                "policy=?,policy_version=?,provider_id=?,available_at=?,updated_at=? WHERE id=?",
                (
                    dumps(policy),
                    policy["version"],
                    self.answer.settings.provider_id(config),
                    self.clock(),
                    self.clock(),
                    jid,
                ),
            )
        self.wake.set()
        return self.public(self.c.db.one("SELECT * FROM meeting_jobs WHERE id=?", (jid,)))

    def list(self, wid, sid, principal, cursor=None, limit=15, include_anchor=False):
        self._session_access(sid, principal)
        self.c.workspaces.get(wid)
        condition = "workspace_id=? AND session_id=? AND state NOT IN ('SUPERSEDED','CANCELLED')"
        args = [wid, sid]
        condition += " AND owner=?"
        args.append(principal.subject)
        total = self.c.db.one(f"SELECT COUNT(*) n FROM meeting_jobs WHERE {condition}", tuple(args))["n"]
        anchor = None
        if cursor:
            anchor_condition = condition.replace(" AND state NOT IN ('SUPERSEDED','CANCELLED')", "")
            before = self.c.db.one(
                f"SELECT * FROM meeting_jobs WHERE {anchor_condition} AND id=?", (*args, cursor)
            )
            if not before:
                raise RagError("INVALID_CURSOR", status=409)
            if include_anchor and before["state"] not in {"SUPERSEDED", "CANCELLED"}:
                anchor = before
            condition += " AND (created_at<? OR (created_at=? AND id<?))"
            args.extend((before["created_at"], before["created_at"], before["id"]))
        rows = self.c.db.all(
            f"SELECT * FROM meeting_jobs WHERE {condition} ORDER BY created_at DESC,id DESC LIMIT ?",
            (*args, limit + 1),
        )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = rows[-1]["id"] if more else None
        if anchor:
            rows.insert(0, anchor)
        public = []
        for row in rows:
            item = self.public(row)
            # Revalidate source/consent even for already-completed cached results.
            try:
                self.meeting.approved_config(wid)
                self.c.revisions.resolve(wid, json.loads(row["input"])["revision_id"])
            except RagError:
                item.update(result=None, reason="SOURCE_OR_CONSENT_CHANGED")
            public.append(item)
        return {
            "jobs": public,
            "scheduler": self.stats(wid),
            "policy": self.policies.get(wid),
            "next_cursor": next_cursor,
            "total": total,
        }

    @staticmethod
    def public(row):
        keys = (
            "id",
            "workspace_id",
            "session_id",
            "utterance_id",
            "utterance_revision",
            "source_key",
            "text",
            "score",
            "queue_class",
            "state",
            "stage",
            "deadline_at",
            "reason",
            "created_at",
            "updated_at",
            "origin",
            "received_at",
            "attempts",
        )
        return {
            **{key: row[key] for key in keys},
            "deadline_missed": bool(row["deadline_missed"]),
            "classification": json.loads(row["classification"]) if row["classification"] else None,
            "result": json.loads(row["result"]) if row["result"] else None,
        }

    def stats(self, wid, rows=None):
        rows = (
            rows
            if rows is not None
            else self.c.db.all(
                "SELECT * FROM meeting_jobs WHERE workspace_id=? AND state NOT IN "
                "('COMPLETED','FAILED','CANCELLED','SUPERSEDED')",
                (wid,),
            )
        )
        active = [r for r in rows if r["state"] not in TERMINAL]
        sq = [r for r in active if r["queue_class"] == "SQ"]
        return {
            "mode": self.modes.get(wid, "NORMAL"),
            "pq_pending": sum(r["queue_class"] == "PQ" for r in active),
            "sq_pending": len(sq),
            "filter_pending": sum(r["queue_class"] is None for r in active),
            "oldest_sq_seconds": max((self.clock() - r["created_at"] for r in sq), default=0),
        }

    def policy_changed(self, wid, old_policy):
        new_policy = self.policies.get(wid)
        if all(new_policy[k] == old_policy[k] for k in ("scope_profile", "filter_model")):
            return
        # Timings remain snapshotted. A semantic scope/model change requires reclassification.
        now = self.clock()
        with self.c.db.transaction():
            rows = self.c.db.all(
                "SELECT j.* FROM meeting_jobs j JOIN meeting_subscriptions s "
                "ON s.workspace_id=j.workspace_id AND s.session_id=j.session_id "
                "WHERE j.workspace_id=? AND s.enabled=1 AND j.state NOT IN ('SUPERSEDED','CANCELLED')",
                (wid,),
            )
            for row in rows:
                # Preserve original deadline: administration cannot erase lateness.
                self.c.db.execute(
                    "UPDATE meeting_jobs SET state='QUEUED',stage='classify',score=NULL,classification=NULL,"
                    "queue_class=NULL,lease_token=NULL,checkpoint=NULL,result=NULL,reason=NULL,"
                    "policy_version=?,policy=?,available_at=?,updated_at=?,attempts=0 WHERE id=?",
                    (
                        new_policy["version"],
                        dumps(
                            {
                                **json.loads(row["policy"]),
                                "scope_profile": new_policy["scope_profile"],
                                "filter_model": new_policy["filter_model"],
                                "version": new_policy["version"],
                            }
                        ),
                        now,
                        now,
                        row["id"],
                    ),
                )
        self.wake.set()

    def _active(self, jid, token):
        row = self.c.db.one("SELECT * FROM meeting_jobs WHERE id=? AND lease_token=?", (jid, token))
        if not row or row["state"] in TERMINAL:
            raise RagError("STALE_UTTERANCE", status=409)
        grant = self.c.db.one(
            "SELECT * FROM meeting_subscriptions WHERE workspace_id=? AND session_id=?",
            (row["workspace_id"], row["session_id"]),
        )
        if not grant or not grant["enabled"] or not self._owner_valid(row["owner"]):
            raise RagError("MEETING_CANCELLED", status=409)
        self.meeting.approved_config(row["workspace_id"])
        config, _ = self.answer.settings.snapshot()
        if row["provider_id"] != self.answer.settings.provider_id(config):
            raise RagError("SETTINGS_CHANGED", status=409)
        self.c.revisions.resolve(row["workspace_id"], json.loads(row["input"])["revision_id"])
        return row

    def _update(self, row, **values):
        values["updated_at"] = self.clock()
        if values.get("state") in {"COMPLETED", "FAILED"} and (
            values.get("queue_class", row["queue_class"]) == "PQ" or row["stage"] == "classify"
        ):
            values["deadline_missed"] = int(
                bool(row["deadline_missed"]) or self.clock() >= row["deadline_at"]
            )
        assignments = ",".join(f"{key}=?" for key in values)
        return self.c.db.execute(
            f"UPDATE meeting_jobs SET {assignments} WHERE id=? AND lease_token=?",
            (*values.values(), row["id"], row["lease_token"]),
        ).rowcount

    def _result(self, row, status, reason, message=None):
        data = json.loads(row["input"])
        return {
            "workspace_id": row["workspace_id"],
            "session_id": row["session_id"],
            "utterance_id": row["utterance_id"],
            "utterance_revision": row["utterance_revision"],
            "revision_id": data["revision_id"],
            "request_id": row["id"],
            "status": status,
            "reason": reason,
            "message": message,
            "popup": None,
            "evidence": [],
            "timings_ms": {},
        }

    def _execute(self, row, lane):
        started = time.monotonic()
        shared_gate = False
        try:
            row = self._active(row["id"], row["lease_token"])
            data, policy = json.loads(row["input"]), json.loads(row["policy"])
            body = meeting_body(data)
            if row["stage"] in {"classify", "generate"}:
                shared_gate = self.answer.factory.gate.acquire(blocking=False)
                if not shared_gate:
                    self._update(row, state="QUEUED", available_at=self.clock() + 0.25, lease_token=None)
                    return
            if row["stage"] == "classify":
                classification = self.classifier.classify(
                    row["workspace_id"],
                    body,
                    scope=policy["scope_profile"],
                    model=policy["filter_model"],
                    following=data.get("following_context", []),
                    addressed_to_ai=data.get("addressed_to_ai", False),
                    timeout_seconds=self._budget(row, policy["filter_timeout_seconds"]),
                ).model_dump()
                self._active(row["id"], row["lease_token"])
                score = classification["score"]
                common = {
                    "classification": dumps(classification),
                    "score": score,
                    "attempts": 0,
                    "queue_class": "PQ" if score and score >= 4 else "SQ" if score == 3 else None,
                }
                if score is None:
                    self._update(
                        row,
                        **common,
                        stage="context",
                        state="AWAITING_CONTEXT",
                        available_at=self.clock() + policy["context_wait_seconds"],
                        reason="NEEDS_CONTEXT",
                        lease_token=None,
                    )
                elif score >= 4 and not classification.get("action_supported", True):
                    self._update(
                        row,
                        **common,
                        state="COMPLETED",
                        stage="done",
                        lease_token=None,
                        result=dumps(
                            self._result(
                                row,
                                "unsupported_action",
                                "UNSUPPORTED_ACTION",
                                "이 회의 도우미는 자료 조회만 지원합니다.",
                            )
                        ),
                        reason="UNSUPPORTED_ACTION",
                    )
                elif score <= 2:
                    self._update(
                        row,
                        **common,
                        state="COMPLETED",
                        stage="done",
                        lease_token=None,
                        result=dumps(self._result(row, "suppressed", "LOW_PRIORITY_RECORDED")),
                        reason="LOW_PRIORITY_RECORDED",
                    )
                else:
                    self._update(
                        row,
                        **common,
                        stage="retrieve",
                        state="QUEUED",
                        lease_token=None,
                        available_at=self.clock(),
                        reason=None,
                    )
            elif row["stage"] == "context":
                self._update(
                    row,
                    state="COMPLETED",
                    stage="done",
                    lease_token=None,
                    result=dumps(
                        self._result(
                            row,
                            "needs_clarification",
                            "NEEDS_CONTEXT",
                            "우리 서비스 기준인가요, 개인 프로젝트 기준인가요?",
                        )
                    ),
                )
            elif row["stage"] == "retrieve":
                reservation = self.c.retrieval.priority_lane() if lane == "priority" else nullcontext()
                with reservation:
                    result = self.meeting.retrieve_classified(
                        row["workspace_id"], body, extracted(json.loads(row["classification"]))
                    )
                self._active(row["id"], row["lease_token"])
                if result["status"] == "ready_for_generation":
                    self._update(
                        row,
                        checkpoint=dumps(result),
                        stage="generate",
                        state="QUEUED",
                        attempts=0,
                        available_at=self.clock(),
                        lease_token=None,
                    )
                else:
                    self._finish(row, result)
            else:
                result = self.meeting.generate_classified(
                    row["workspace_id"],
                    body,
                    extracted(json.loads(row["classification"])),
                    json.loads(row["checkpoint"]),
                    timeout_seconds=self._budget(row, policy["generation_timeout_seconds"]),
                )
                self._active(row["id"], row["lease_token"])
                self._finish(row, result)
        except Exception as exc:
            from .answers import classify

            reason = getattr(exc, "code", None) or classify(exc)
            if reason in {"STALE_UTTERANCE", "MEETING_CANCELLED"}:
                self._update(
                    row, state="CANCELLED", lease_token=None, result=None, checkpoint=None, reason=reason
                )
            else:
                attempts = row["attempts"] + 1
                retry = reason in TRANSIENT and attempts < 2
                self._update(
                    row,
                    state="RETRY_WAIT" if retry else "FAILED",
                    attempts=attempts,
                    available_at=self.clock() + 1.5 + int(row["id"][:2], 16) / 255,
                    reason=reason,
                    lease_token=None,
                )
        finally:
            if shared_gate:
                self.answer.factory.gate.release()
            # Actual running time is charged, including failed calls and non-cancellable calls.
            with self.usage_lock:
                usage = self.usage[lane]
                usage[row["workspace_id"]] = usage.get(row["workspace_id"], 0) + time.monotonic() - started
            self.wake.set()

    def _budget(self, row, cap):
        # Keep an on-time stage within the remaining end-to-end budget. After a
        # missed deadline, bounded continuation still produces the promised result.
        if row["queue_class"] == "SQ":
            return cap
        remaining = row["deadline_at"] - self.clock() - 0.1
        return min(cap, remaining) if remaining >= 1 else cap

    def _finish(self, row, result):
        if result.get("status") == "unavailable":
            raise RagError(result.get("reason") or "LLM_UNAVAILABLE")
        if row["queue_class"] == "SQ" and result.get("status") == "suppressed":
            result = {**result, "status": "insufficient_evidence", "reason": "NO_RELEVANT_SUPPORT"}
        self._update(
            row,
            state="COMPLETED",
            stage="done",
            attempts=0,
            result=dumps(result),
            lease_token=None,
            reason=result.get("reason"),
        )

    def _mode(self, wid, jobs, now):
        urgent = [r for r in jobs if r["queue_class"] == "PQ" or r["stage"] == "classify"]
        current = self.modes.get(wid, "NORMAL")
        if urgent:
            policy = json.loads(urgent[0]["policy"])
            ratios = [
                (now - r["received_at"]) / json.loads(r["policy"])["priority_response_target_seconds"]
                for r in urgent
            ]
            # Conservative initial estimates, replaced by measured stage timing in future calibration.
            risk = any(
                r["deadline_at"] - now < {"classify": 3, "retrieve": 3, "generate": 2}.get(r["stage"], 0)
                for r in urgent
            )
            age = max(ratios)
            if age >= policy["protect_ratio"] or risk:
                self.recovery_since.pop(wid, None)
                self.modes[wid] = "PQ_ONLY"
                return "PQ_ONLY"
            if age >= policy["pressure_ratio"]:
                self.recovery_since.pop(wid, None)
                self.modes[wid] = "PRESSURED"
                return "PRESSURED"
            recovered = age < policy["recovery_ratio"]
        else:
            policy = self.policies.get(wid)
            recovered = True
        if current != "NORMAL":
            if not recovered:
                return current
            began = self.recovery_since.setdefault(wid, now)
            if now - began < policy["recovery_seconds"]:
                self.modes[wid] = "RECOVERY"
                return "RECOVERY"
        self.modes[wid] = "NORMAL"
        self.recovery_since.pop(wid, None)
        return "NORMAL"

    def _pick(self, jobs, lane):
        if not jobs:
            return None
        # Fair workspace selection, then earliest deadline; score only breaks deadline ties.
        with self.usage_lock:
            usage = dict(self.usage[lane])
        wid = min(
            {r["workspace_id"] for r in jobs},
            key=lambda w: (
                usage.get(w, 0),
                min(r["created_at"] for r in jobs if r["workspace_id"] == w),
            ),
        )
        local = [r for r in jobs if r["workspace_id"] == wid]
        if lane == "filter":
            return min(local, key=lambda r: (r["origin"] == "file", r["received_at"]))
        return min(local, key=lambda r: (r["queue_class"] != "PQ", r["deadline_at"], -(r["score"] or 0)))

    def tick(self):
        now = self.clock()
        # This timer is independent of workers, including blocked classifier and remote generation calls.
        self.c.db.execute(
            "UPDATE meeting_jobs SET deadline_missed=1,updated_at=? WHERE deadline_at<=? "
            "AND deadline_missed=0 AND state NOT IN ('COMPLETED','FAILED','CANCELLED','SUPERSEDED') "
            "AND (queue_class='PQ' OR stage='classify')",
            (now, now),
        )
        for lane, future in list(self.running.items()):
            if future.done():
                future.result()
                del self.running[lane]
        jobs = self.c.db.all(
            "SELECT * FROM meeting_jobs WHERE state NOT IN ('COMPLETED','FAILED','CANCELLED','SUPERSEDED')",
        )
        modes = {}
        for wid in {r["workspace_id"] for r in jobs} | set(self.modes):
            try:
                modes[wid] = self._mode(
                    wid,
                    [
                        r
                        for r in jobs
                        if r["workspace_id"] == wid
                        and (r["available_at"] <= now or r["state"] in {"RUNNING", "CLASSIFYING"})
                    ],
                    now,
                )
            except RagError:
                self.modes.pop(wid, None)
        available = [r for r in jobs if r["state"] in RUNNABLE and r["available_at"] <= now]
        for slot in (*FILTER_SLOTS, "priority", "shared"):
            if slot in self.running:
                continue
            lane = "filter" if slot in FILTER_SLOTS else slot
            if lane == "filter":
                candidates = [r for r in available if r["stage"] in {"classify", "context"}]
                live = [r for r in candidates if r["origin"] == "live"]
                candidates = live or candidates
            elif lane == "priority":
                candidates = [r for r in available if r["queue_class"] == "PQ" and r["origin"] == "live"]
            else:
                main = [
                    r for r in available if r["queue_class"] and r["stage"] not in {"classify", "context"}
                ]
                candidates = [r for r in main if r["queue_class"] == "PQ"]
                if not candidates and not any(
                    m in {"PQ_ONLY", "PRESSURED", "RECOVERY"} for m in modes.values()
                ):
                    candidates = [r for r in main if modes.get(r["workspace_id"], "NORMAL") == "NORMAL"]
                for r in main:
                    if r["queue_class"] == "SQ" and any(
                        m in {"PQ_ONLY", "PRESSURED"} for m in modes.values()
                    ):
                        self.c.db.execute(
                            "UPDATE meeting_jobs SET state='PAUSED' WHERE id=? AND state='QUEUED'", (r["id"],)
                        )
            picked = self._pick(candidates, lane)
            if not picked:
                continue
            token = uid()
            with self.c.db.transaction():
                changed = self.c.db.execute(
                    "UPDATE meeting_jobs SET state=?,lease_token=?,updated_at=? WHERE id=? "
                    "AND state IN ('QUEUED','PAUSED','RETRY_WAIT','AWAITING_CONTEXT')",
                    ("CLASSIFYING" if lane == "filter" else "RUNNING", token, now, picked["id"]),
                ).rowcount
            if changed:
                picked.update(lease_token=token)
                self.running[slot] = self.pool.submit(self._execute, picked, lane)
                available = [r for r in available if r["id"] != picked["id"]]

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception as exc:
                if self.c.db.audit:
                    self.c.db.audit.emit("meeting.scheduler_error", error_type=type(exc).__name__)
            self.wake.wait(0.1)
            self.wake.clear()
