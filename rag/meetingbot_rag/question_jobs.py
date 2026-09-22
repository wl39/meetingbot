"""SQLite-backed FIFO messages and three bounded consumers in the owning RAG process.

The service.lock excludes a second process. Only claimed messages enter memory;
pending work and its account-owned result survive HTTP disconnects and restarts.
"""

import json
import threading
import time

from meetingbot_access import Principal

from .db import dumps
from .sources import RagError
from .workspace_access import visible

LLM_CONCURRENCY = 3


class QuestionJobs:
    def __init__(self, core, answer, history, access):
        self.c, self.answer, self.history, self.access = core, answer, history, access
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.threads = []
        core.db.execute(
            "UPDATE query_runs SET result=json_set(result,'$.status','queued'),available_at=0 "
            "WHERE input IS NOT NULL AND json_extract(result,'$.status')='processing'"
        )

    def start(self):
        for index in range(LLM_CONCURRENCY):
            thread = threading.Thread(target=self._loop, name=f"question-worker-{index + 1}", daemon=True)
            self.threads.append(thread)
            thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        for thread in self.threads:
            thread.join()

    def enqueue(self, wid, body, principal, idempotency_key=None):
        result = self.history.create(wid, body, principal, "question", queued=True,
                                     idempotency_key=idempotency_key)
        self.wake.set()
        return result

    def _principal(self, row):
        subject = row["subject"]
        if subject == "superadmin":
            return Principal(subject, "superadmin")
        with self.access.db() as db:
            if subject.startswith("guest_"):
                account = db.execute("SELECT 1 FROM access_sessions WHERE subject=? AND expires>?",
                                     (subject, time.time())).fetchone()
                if account:
                    return Principal(subject, "visitor", guest=True)
            else:
                account = db.execute("SELECT role FROM access_keys WHERE id=? AND revoked IS NULL",
                                     (subject,)).fetchone()
                if account:
                    return Principal(subject, account["role"])
        raise RagError("AUTH_REQUIRED", "요청한 계정의 접근 권한이 만료되었습니다.", 401)

    def _ready(self):
        return self.c.db.one(
            "SELECT id FROM query_runs WHERE input IS NOT NULL "
            "AND json_extract(result,'$.status')='queued' AND available_at<=? LIMIT 1", (time.time(),)
        )

    def _claim(self):
        with self.c.db.transaction():
            row = self.c.db.one(
                "SELECT * FROM query_runs WHERE input IS NOT NULL "
                "AND json_extract(result,'$.status')='queued' AND available_at<=? "
                "ORDER BY created_at,id LIMIT 1", (time.time(),)
            )
            if row:
                self.c.db.execute(
                    "UPDATE query_runs SET result=json_set(result,'$.status','processing') WHERE id=?",
                    (row["id"],),
                )
            return row

    def _execute(self, row):
        result = json.loads(row["result"])
        available_at = 0
        try:
            principal = self._principal(row)
            if not visible(self.c, principal, row["workspace_id"]):
                raise RagError("NOT_FOUND", "자료에 접근할 수 없습니다.", 404)
            result = {**result, **self.answer.answer(
                row["workspace_id"], **json.loads(row["input"])["resolved"], slot_reserved=True
            ), "request_id": row["id"], "created_at": row["created_at"], "kind": "question"}
        except RagError as error:
            if error.code == "SEARCH_BUSY":
                result.update(status="queued")
                available_at = time.time() + 0.25
            else:
                result.update(status="failed", reason=error.code, answer=error.message)
        except Exception:
            result.update(status="failed", reason="REQUEST_FAILED",
                          answer="요청을 완료하지 못했습니다. 다시 시도해 주세요.")
        # UPDATE only: deletion during a slow external request can never recreate the record.
        with self.c.workspaces.locks[row["workspace_id"]]:
            self.c.db.execute(
                "UPDATE query_runs SET result=?,revision_id=?,available_at=? WHERE id=?",
                (dumps(result), result.get("revision_id"), available_at, row["id"]),
            )

    def _loop(self):
        while not self.stop.is_set():
            # Share the same cap with meeting classification, generation and diagnostic calls.
            # Busy work remains in the durable queue, without consuming an HTTP worker.
            row = None
            try:
                if self._ready() and self.answer.factory.gate.acquire(blocking=False):
                    try:
                        row = self._claim() if not self.stop.is_set() else None
                        if row:
                            self._execute(row)
                            continue
                    finally:
                        self.answer.factory.gate.release()
            except Exception as error:
                self._log_error(error)
                if row:
                    try:
                        self.c.db.execute(
                            "UPDATE query_runs SET result=json_set(result,'$.status','queued'),available_at=? "
                            "WHERE id=? AND json_extract(result,'$.status')='processing'",
                            (time.time() + 1, row["id"]),
                        )
                    except Exception as retry_error:
                        self._log_error(retry_error)
            self.wake.wait(0.2)
            self.wake.clear()

    def _log_error(self, error):
        if self.c.db.audit:
            self.c.db.audit.emit("question.worker_error", error_type=type(error).__name__)
