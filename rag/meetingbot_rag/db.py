import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


def uid():
    return uuid.uuid4().hex


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str)


@contextmanager
def open_database(path, *, readonly=False):
    """Commit/rollback and close short-lived connections, releasing Windows file locks."""
    target = Path(path).resolve().as_uri() + "?mode=ro" if readonly else path
    with closing(sqlite3.connect(target, uri=readonly)) as connection, connection:
        yield connection


SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS workspaces(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, created_at REAL,
 consent TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS knowledge_bases(
 id TEXT PRIMARY KEY, workspace_id TEXT UNIQUE REFERENCES workspaces(id), active_revision_id TEXT);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY, workspace_id TEXT UNIQUE REFERENCES workspaces(id), root_id TEXT,
 relative_path TEXT, policy TEXT);
CREATE TABLE IF NOT EXISTS revisions(
 id TEXT PRIMARY KEY, workspace_id TEXT REFERENCES workspaces(id), state TEXT,
 fingerprint TEXT, config TEXT, created_at REAL, manifest TEXT, pinned INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS documents(
 id TEXT PRIMARY KEY, workspace_id TEXT, relative_path TEXT, UNIQUE(workspace_id,relative_path));
CREATE TABLE IF NOT EXISTS document_versions(
 id TEXT PRIMARY KEY, workspace_id TEXT, document_id TEXT, content_hash TEXT,
 fingerprint TEXT, snapshot TEXT, parsed TEXT, chunks TEXT);
CREATE INDEX IF NOT EXISTS dv_reuse ON document_versions(workspace_id,document_id,content_hash,fingerprint);
CREATE TABLE IF NOT EXISTS jobs(
 id TEXT PRIMARY KEY, workspace_id TEXT, revision_id TEXT, kind TEXT, state TEXT,
 created_at REAL, updated_at REAL, heartbeat REAL, payload TEXT, result TEXT,
 cancel INTEGER NOT NULL DEFAULT 0, idempotency_key TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS job_idempotency ON jobs(workspace_id,idempotency_key)
 WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS query_runs(
 id TEXT PRIMARY KEY, workspace_id TEXT, revision_id TEXT, created_at REAL, result TEXT);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, csrf TEXT, expires REAL);
"""


class Database:
    def __init__(self, path, audit=None):
        self.audit = audit
        self.transaction_id = None
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)
        version = self.one("SELECT version FROM schema_version")["version"]
        if version == 1:
            migration = (Path(__file__).parent / "migrations/002_llm_management.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 2
        if version == 2:
            migration = (Path(__file__).parent / "migrations/003_folder_uploads.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 3
        if version == 3:
            migration = (Path(__file__).parent / "migrations/004_rag_settings.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 4
        if version == 4:
            migration = (Path(__file__).parent / "migrations/005_workspace_guides.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 5
        if version == 5:
            migration = (Path(__file__).parent / "migrations/006_meeting_queue.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 6
        if version == 6:
            migration = (Path(__file__).parent / "migrations/007_upload_owners.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 7
        if version == 7:
            migration = (Path(__file__).parent / "migrations/008_question_history.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 8
        if version == 8:
            migration = (Path(__file__).parent / "migrations/009_question_queue.sql").read_text(encoding="utf-8")
            self.conn.executescript("BEGIN IMMEDIATE;\n" + migration + "\nCOMMIT;")
            version = 9
        if version != 9:
            raise RuntimeError("Unsupported database version")

    @contextmanager
    def transaction(self):
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            self.transaction_id = uid()
            try:
                yield self
                self.conn.execute("COMMIT")
                self.record("rag.transaction", outcome="committed")
            except BaseException:
                self.conn.execute("ROLLBACK")
                self.record("rag.transaction", outcome="rolled_back")
                raise
            finally:
                self.transaction_id = None

    def record(self, event, **fields):
        if self.audit:
            self.audit.emit(event, transaction_id=self.transaction_id, **fields)

    def execute(self, sql, args=()):
        with self.lock:
            match = re.match(r"\s*(INSERT(?: OR \w+)? INTO|UPDATE|DELETE FROM)\s+(\w+)", sql, re.I)
            try:
                result = self.conn.execute(sql, args)
            except Exception as exc:
                self.record("rag.database_failed", error_type=type(exc).__name__)
                raise
            if match:
                self.record("rag.database_write", operation=match[1].split()[0].upper(),
                            table=match[2], rows=result.rowcount,
                            outcome="pending" if self.transaction_id else "committed")
            return result

    def all(self, sql, args=()):
        with self.lock:
            return [dict(x) for x in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def recover(self):
        with self.transaction():
            self.execute(
                "UPDATE query_runs SET result=json_set(result,'$.status','failed',"
                "'$.reason','SERVER_RESTARTED','$.answer',?) WHERE input IS NULL "
                "AND json_extract(result,'$.status')='processing'",
                ("서버가 재시작되어 요청을 완료하지 못했습니다. 다시 질문해 주세요.",),
            )
            self.execute(
                "UPDATE jobs SET state='FAILED', result=?, updated_at=? WHERE state IN ('QUEUED','RUNNING')",
                (
                    dumps(
                        {
                            "error_code": "SERVER_RESTARTED",
                            "message": "서버가 재시작되었습니다. 재시도하세요.",
                        }
                    ),
                    time.time(),
                ),
            )
            self.execute(
                "UPDATE revisions SET state='FAILED' WHERE state IN "
                "('REGISTERED','SCANNING','BUILDING','VALIDATING')"
            )

    def close(self):
        self.conn.close()
