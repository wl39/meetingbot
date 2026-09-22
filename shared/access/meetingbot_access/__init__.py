"""Shared, revocable roles, browser sessions and demo quotas for both APIs."""

import hashlib
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

ROLES = ("visitor", "admin", "superadmin")
COOKIE = "meetingbot_session"
GUEST_SESSION_SECONDS = 30 * 86400


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    key_hash: str = ""
    csrf: str = ""
    guest: bool = False

    @property
    def manages_data(self):
        return self.role in {"admin", "superadmin"}


class AccessStore:
    def __init__(self, token_file, database=None, audit=None):
        self.audit = audit
        self.token_file = Path(token_file)
        self.path = Path(database) if database else self.token_file.parent / "access.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS access_keys(
                    id TEXT PRIMARY KEY, label TEXT, role TEXT, hash TEXT UNIQUE,
                    created REAL, revoked REAL);
                CREATE TABLE IF NOT EXISTS access_sessions(
                    hash TEXT PRIMARY KEY, subject TEXT, key_hash TEXT, csrf TEXT,
                    expires REAL, guest INTEGER);
                CREATE TABLE IF NOT EXISTS access_quota(
                    subject TEXT, category TEXT, day INTEGER, count INTEGER,
                    PRIMARY KEY(subject, category, day));
                CREATE TABLE IF NOT EXISTS access_owners(
                    resource TEXT PRIMARY KEY, subject TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS appearance_settings(
                    id INTEGER PRIMARY KEY CHECK(id=1), color TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS service_secrets(
                    name TEXT PRIMARY KEY, secret TEXT NOT NULL);
            """)
        self.path.chmod(0o600)

    def service_secret(self, name):
        """Persistent server-only credentials, independent of every user access key.

        Both services share this private database. INSERT OR IGNORE selects the
        same secret even when separate processes start concurrently; a restart
        never rotates a credential while the other service is still running.
        This method is intentionally not exposed by any account/settings API.
        """
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO service_secrets VALUES(?,?)",
                       (name, secrets.token_urlsafe(32)))
            row = db.execute("SELECT secret FROM service_secrets WHERE name=?", (name,)).fetchone()
        return row["secret"]

    def record(self, event, **fields):
        if self.audit:
            self.audit.emit(event, **fields)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def by_hash(self, hashed):
        # The existing installation key remains its superadministrator key.
        if hashed and secrets.compare_digest(hashed, digest(self.token_file.read_text().strip())):
            return Principal("superadmin", "superadmin", hashed)
        with self.db() as db:
            row = db.execute("SELECT * FROM access_keys WHERE hash=? AND revoked IS NULL", (hashed,)).fetchone()
        return Principal(row["id"], row["role"], hashed) if row else None

    def key(self, value):
        principal = self.by_hash(digest(value)) if value else None
        if value and not principal:
            self.record("auth.key_rejected", authenticated=False)
        return principal

    def issue_key(self, label, role):
        if role not in ROLES or not 1 <= len(label.strip()) <= 80:
            raise ValueError("INVALID_ACCESS_KEY")
        key, kid = secrets.token_urlsafe(32), secrets.token_hex(16)
        with self.db() as db:
            db.execute("INSERT INTO access_keys VALUES(?,?,?,?,?,NULL)",
                       (kid, label.strip(), role, digest(key), time.time()))
        self.record("auth.key_created", subject=kid, role=role)
        return {"id": kid, "label": label.strip(), "role": role, "key": key}

    def keys(self):
        with self.db() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,label,role,created,revoked FROM access_keys ORDER BY created DESC")]

    def revoke(self, kid):
        with self.db() as db:
            revoked = db.execute("UPDATE access_keys SET revoked=? WHERE id=? AND revoked IS NULL",
                                 (time.time(), kid)).rowcount > 0
        self.record("auth.key_revoked", subject=kid, outcome="revoked" if revoked else "not_found")
        return revoked

    def profile(self, principal):
        if principal.subject == "superadmin":
            label = "운영 관리자"
        elif principal.guest:
            label = "방문자 " + principal.subject.removeprefix("guest_")[:8]
        else:
            with self.db() as db:
                row = db.execute("SELECT label FROM access_keys WHERE id=?", (principal.subject,)).fetchone()
            label = row["label"] if row else "계정 " + principal.subject[:8]
        return {"id": principal.subject, "label": label, "role": principal.role}

    def issue_session(self, principal=None, seconds=None):
        if seconds is None:
            seconds = 43200 if principal else GUEST_SESSION_SECONDS
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        subject = principal.subject if principal else "guest_" + secrets.token_hex(16)
        with self.db() as db:
            db.execute("DELETE FROM access_sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO access_sessions VALUES(?,?,?,?,?,?)",
                       (digest(token), subject, principal.key_hash if principal else "", csrf,
                        time.time() + seconds, int(principal is None)))
        self.record("auth.session_created", subject=subject, role=principal.role if principal else "visitor",
                    keyless=principal is None)
        return token, Principal(subject, principal.role if principal else "visitor",
                                principal.key_hash if principal else "", csrf, principal is None)

    def session(self, token, allow_guest=False):
        if not token:
            return None
        with self.db() as db:
            row = db.execute("SELECT * FROM access_sessions WHERE hash=? AND expires>?",
                             (digest(token), time.time())).fetchone()
        if not row or (row["guest"] and not allow_guest):
            return None
        principal = None if row["guest"] else self.by_hash(row["key_hash"])
        if not row["guest"] and not principal:
            return None
        return Principal(row["subject"], principal.role if principal else "visitor",
                         row["key_hash"], row["csrf"], bool(row["guest"]))

    def logout(self, token):
        with self.db() as db:
            deleted = db.execute("DELETE FROM access_sessions WHERE hash=?", (digest(token),)).rowcount
        self.record("auth.logout", count=deleted)

    def renew_guest(self, token):
        with self.db() as db:
            db.execute("UPDATE access_sessions SET expires=? WHERE hash=? AND guest=1 AND expires>?",
                       (time.time() + GUEST_SESSION_SECONDS, digest(token), time.time()))

    def owner(self, resource, subject=None):
        with self.db() as db:
            if subject:
                db.execute("INSERT OR IGNORE INTO access_owners VALUES(?,?)", (resource, subject))
            row = db.execute("SELECT subject FROM access_owners WHERE resource=?", (resource,)).fetchone()
        return row["subject"] if row else None

    def theme(self, color=None):
        with self.db() as db:
            if color is not None:
                db.execute("INSERT INTO appearance_settings VALUES(1,?) ON CONFLICT(id) "
                           "DO UPDATE SET color=excluded.color", (color.lower(),))
            row = db.execute("SELECT color FROM appearance_settings WHERE id=1").fetchone()
        return {"color": row["color"] if row else "#b85c12"}

    def consume(self, subject, category, limit, global_limit):
        """Atomic persistent per-identity and instance limits. New cookies cannot reset the latter."""
        day = int(time.time() // 86400)
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM access_quota WHERE day<?", (day - 2,))
            for owner, cap in ((subject, limit), ("*", global_limit)):
                row = db.execute("SELECT count FROM access_quota WHERE subject=? AND category=? AND day=?",
                                 (owner, category, day)).fetchone()
                if row and row["count"] >= cap:
                    self.record("quota.denied", subject=subject, action=category)
                    return False
            for owner in (subject, "*"):
                db.execute("INSERT INTO access_quota VALUES(?,?,?,1) ON CONFLICT(subject,category,day) "
                           "DO UPDATE SET count=count+1", (owner, category, day))
        return True


def rag_allowed(role, method, path):
    """Explicit visitor allowlist; new endpoints never become public accidentally."""
    import re

    if role == "superadmin":
        return True
    if path in {"/api/rag/auth/session", "/api/rag/auth/logout"}:
        return True
    if method == "GET" and (path == "/api/rag/history" or re.fullmatch(r"/api/rag/history/(?:filters|[a-f0-9]{32})", path)):
        # The service checks the record owner and restricts scope=all to managers.
        return True
    if role == "admin":
        return any(path == prefix or path.startswith(prefix + "/") for prefix in (
            "/api/rag/workspaces", "/api/rag/uploads", "/api/rag/source-roots", "/api/rag/source-previews"
        )) or (method == "GET" and path in {"/api/rag/diagnostics", "/api/rag/embedding"})
    # Ownership is checked again by the RAG service for these visitor routes.
    if path == "/api/rag/uploads":
        return method == "POST"
    if path == "/api/rag/uploads/limits":
        return method == "GET"
    if re.fullmatch(r"/api/rag/uploads/[a-f0-9]{32}", path):
        return method in {"GET", "DELETE"}
    if re.fullmatch(r"/api/rag/uploads/[a-f0-9]{32}/files/[a-f0-9]{32}", path):
        return method == "PUT"
    if re.fullmatch(r"/api/rag/uploads/[a-f0-9]{32}/commit", path):
        return method == "POST"
    if re.fullmatch(r"/api/rag/workspaces/[a-f0-9]{32}", path) and method in {"PATCH", "DELETE"}:
        return True
    if re.fullmatch(r"/api/rag/workspaces/[a-f0-9]{32}/guide", path):
        return method in {"GET", "PUT"}
    if method == "POST" and re.fullmatch(
        r"/api/rag/workspaces/[a-f0-9]{32}/index-jobs(?:/[a-f0-9]{32}/cancel)?", path
    ):
        return True
    if method == "GET":
        if re.fullmatch(r"/api/rag/workspaces/[a-f0-9]{32}/meeting/(?:jobs|policy)", path):
            return True
        return path in {"/api/rag/workspaces", "/api/rag/diagnostics", "/api/rag/embedding"} or bool(re.fullmatch(
            r"/api/rag/workspaces/[a-f0-9]{32}(?:/(?:revisions|documents|questions|evidence/[^/]+|index-jobs/[a-f0-9]{32}))?", path))
    if method == "POST" and re.fullmatch(
        r"/api/rag/workspaces/[a-f0-9]{32}/meeting/(?:jobs(?:/[a-f0-9]{32}/retry)?|"
        r"sessions/[^/]+/(?:subscription|cancel|sync))", path
    ):
        return True
    return method == "POST" and bool(re.fullmatch(
        r"/api/rag/workspaces/[a-f0-9]{32}/(?:search|questions|meeting/analyze)", path))
