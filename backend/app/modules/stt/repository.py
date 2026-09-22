import json
import sqlite3
import time
from collections import defaultdict

from app.contracts.utterance import uid

TERMINAL = {"COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "INTERRUPTED"}


class Conflict(Exception):
    pass


class Repository:
    def __init__(self, path, audit=None):
        self.audit = audit
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, session_id TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY, session_id TEXT,
                utterance_id TEXT, revision INTEGER, data TEXT,
                UNIQUE(session_id, utterance_id, revision));
            CREATE TABLE IF NOT EXISTS meeting_subscriptions(
                session_id TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meeting_deliveries(
                session_id TEXT, source_key TEXT, received_at REAL NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(session_id, source_key));
            CREATE TABLE IF NOT EXISTS meeting_source_clock(
                session_id TEXT, utterance_id TEXT, revision INTEGER, received_at REAL NOT NULL,
                PRIMARY KEY(session_id, utterance_id, revision));
        """)
        for session in self.list():
            if session["state"] not in TERMINAL:
                session["state"] = "INTERRUPTED"
                session["warnings"].append(
                    {"type": "service.restarted", "retry": "원음이 없으면 다시 입력하세요."}
                )
                self.save(session)
        for job_id, raw in self.db.execute("SELECT id, data FROM jobs").fetchall():
            job = json.loads(raw)
            if job["state"] not in TERMINAL:
                self.job(job_id, job["session_id"], "INTERRUPTED", error="SERVICE_RESTARTED")

    def record(self, event, **fields):
        if self.audit:
            self.audit.emit(event, **fields)

    def create(self, mode, options, environment):
        session = {
            "id": uid("session"),
            "mode": mode,
            "state": "CREATED" if mode == "microphone" else "QUEUED",
            "generation": 1,
            "snapshot_revision": 1,
            "options": options,
            "environment": environment,
            "created_at": time.time(),
            "utterances": [],
            "speakers": {},
            "warnings": [],
            "metrics": {},
            "audio_retained": False,
        }
        self.db.execute("INSERT INTO sessions VALUES (?, ?)", (session["id"], json.dumps(session)))
        self.db.commit()
        self.record("stt.session_created", session_id=session["id"], state=session["state"], mode=mode)
        return session

    def get(self, sid):
        row = self.db.execute("SELECT data FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT data FROM sessions ORDER BY rowid DESC")]

    def save(self, session):
        current = self.get(session["id"])
        if current is None:
            return
        session["snapshot_revision"] = current.get("snapshot_revision", 1) + 1
        self.db.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session), session["id"]))
        # The canonical transcript itself is the durable analysis inbox. Arrival clocks and
        # the source snapshot commit together, so a restart cannot lose unforwarded speech.
        now = time.time()
        self.db.executemany(
            "INSERT OR IGNORE INTO meeting_source_clock VALUES(?,?,?,?)",
            [(session["id"], u["utterance_id"], u["revision"], now)
             for u in session["utterances"] if u["status"] in {"stable", "corrected", "final"}],
        )
        self.db.commit()

        self.record("stt.session_updated", session_id=session["id"], state=session["state"],
                    previous_state=current["state"], revision=session["snapshot_revision"])

    def valid(self, sid, generation):
        current = self.get(sid)
        return current and current["generation"] == generation and current["state"] != "CANCELLED"

    def state(self, sid, state, **metrics):
        session = self.get(sid)
        if session:
            session["state"] = state
            session["metrics"].update(metrics)
            self.save(session)

    def warning(self, sid, warning):
        self.record("stt.warning", session_id=sid, code=warning.get("type"))
        session = self.get(sid)
        if session:
            if len(session["warnings"]) < 100:
                session["warnings"].append(warning)
            self.save(session)

    def job(self, jid, sid, state, **extra):
        data = {"id": jid, "session_id": sid, "state": state, **extra}
        self.db.execute(
            "INSERT INTO jobs VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
            (jid, sid, json.dumps(data)),
        )
        self.db.commit()

        self.record("stt.job_updated", job_id=jid, session_id=sid, state=state)

    def get_job(self, jid):
        row = self.db.execute("SELECT data FROM jobs WHERE id=?", (jid,)).fetchone()
        return json.loads(row[0]) if row else None

    def _event(self, event):
        self.record("stt.utterance", session_id=event["session_id"], event_id=event["event_id"],
                    utterance_id=event["utterance_id"], revision=event["revision"], state=event["status"])
        if event["status"] != "partial":
            self.db.execute(
                "INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?, ?)",
                (
                    event["event_id"],
                    event["session_id"],
                    event["utterance_id"],
                    event["revision"],
                    json.dumps(event),
                ),
            )

    def manual_boundaries(self, sid):
        session = self.get(sid)
        return (
            [t for u in session["utterances"] if u["manual_fields"] for t in (u["start_ms"], u["end_ms"])]
            if session
            else []
        )

    def publish(self, sid, generation, candidates):
        if not self.valid(sid, generation):
            return []
        session = self.get(sid)
        old = session["utterances"]
        by_start = defaultdict(list)
        for u in old:
            by_start[u["start_ms"] // 250].append(u)
        output, emitted, used = [], [], set()
        # Manual regions are authoritative, including during subsequent split/merge.
        manual = [u for u in old if u["manual_fields"]]
        candidates = [c.model_dump() for c in candidates]
        for c in candidates:
            if any(c["start_ms"] < u["end_ms"] and c["end_ms"] > u["start_ms"] for u in manual):
                continue
            matches = [
                u
                for bucket in range(c["start_ms"] // 250 - 1, c["start_ms"] // 250 + 2)
                for u in by_start[bucket]
                if u["utterance_id"] not in used
                and not u["manual_fields"]
                and abs(u["start_ms"] - c["start_ms"]) <= 250
                and abs(u["end_ms"] - c["end_ms"]) <= 400
            ]
            if matches:
                prev = matches[0]
                used.add(prev["utterance_id"])
                keys = (
                    "text",
                    "speaker_id",
                    "speaker_status",
                    "start_ms",
                    "end_ms",
                    "status",
                    "overlap",
                    "words",
                )
                changed = [k for k in keys if prev.get(k, []) != c[k]]
                if not changed:
                    output.append(prev)
                    continue
                c.update(
                    utterance_id=prev["utterance_id"], revision=prev["revision"] + 1, changed_fields=changed
                )
            else:
                c["replaces_utterance_ids"] = [
                    u["utterance_id"]
                    for u in old
                    if not u["manual_fields"] and u["start_ms"] < c["end_ms"] and u["end_ms"] > c["start_ms"]
                ]
            output.append(c)
            emitted.append(c)
        for prev in old:
            if prev["manual_fields"]:
                related = [
                    c for c in candidates if c["start_ms"] < prev["end_ms"] and c["end_ms"] > prev["start_ms"]
                ]
                updated = dict(prev)
                if related:
                    if "text" not in prev["manual_fields"]:
                        updated["text"] = " ".join(c["text"] for c in related)
                        updated["words"] = [w for c in related for w in c["words"]]
                    if "speaker_id" not in prev["manual_fields"]:
                        labels = {c["speaker_id"] for c in related}
                        updated["speaker_id"] = next(iter(labels)) if len(labels) == 1 else None
                        updated["speaker_status"] = (
                            related[0]["speaker_status"] if len(labels) == 1 else "unknown"
                        )
                    updated["overlap"] = any(c["overlap"] for c in related)
                changed = [
                    k
                    for k in ("text", "speaker_id", "speaker_status", "overlap", "words")
                    if updated.get(k, []) != prev.get(k, [])
                ]
                if changed:
                    updated.update(event_id=uid("evt"), revision=prev["revision"] + 1, changed_fields=changed)
                    emitted.append(updated)
                output.append(updated)
            elif prev["utterance_id"] not in used:
                event = dict(
                    prev,
                    status="retracted",
                    revision=prev["revision"] + 1,
                    event_id=uid("evt"),
                    changed_fields=["status"],
                )
                emitted.append(event)
        for event in emitted:
            self._event(event)
        session["utterances"] = sorted(output, key=lambda u: u["start_ms"])
        for event in output:
            spk = event["speaker_id"]
            if spk and spk not in session["speakers"]:
                session["speakers"][spk] = f"화자 {chr(65 + len(session['speakers']))}"
        self.save(session)
        return emitted

    def correct(self, sid, utterance_id, patch):
        session = self.get(sid)
        event = next((u for u in session["utterances"] if u["utterance_id"] == utterance_id), None)
        if event is None:
            raise KeyError(utterance_id)
        if event["revision"] != patch.base_revision:
            raise Conflict("REVISION_CONFLICT")
        changes = patch.model_dump(exclude_unset=True)
        changed = []
        if "text" in changes and changes["text"] is not None:
            event["text"] = changes["text"]
            changed.append("text")
            if event.get("words"):
                event["words"] = []
                changed.append("words")
        if "speaker_id" in changes:
            spk = changes["speaker_id"]
            if spk is not None and spk not in session["speakers"]:
                raise ValueError("UNKNOWN_SPEAKER")
            event.update(speaker_id=spk, speaker_status="manual")
            changed.append("speaker_id")
        if not changed:
            raise ValueError("EMPTY_CORRECTION")
        event.update(
            revision=event["revision"] + 1,
            event_id=uid("evt"),
            status="corrected",
            changed_fields=changed,
            manual_fields=sorted(set(event["manual_fields"] + [k for k in changed if k != "words"])),
        )
        self._event(event)
        self.save(session)
        return event

    def events(self, sid):
        return [
            json.loads(r[0])
            for r in self.db.execute("SELECT data FROM events WHERE session_id=? ORDER BY rowid", (sid,))
        ]

    def delete(self, sid):
        subscription = self.meeting_subscription(sid)
        if subscription:
            # Keep the cleanup tombstone until the upstream deletion has been acknowledged.
            subscription.update(enabled=False, deleted=True, cleanup_pending=True)
            subscription["pending_cleanup"] = [wid for wid in subscription.get("workspaces", [])
                                                if wid != subscription["workspace_id"]]
            self.db.execute("UPDATE meeting_subscriptions SET data=? WHERE session_id=?",
                            (json.dumps(subscription), sid))
        self.db.execute("DELETE FROM events WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM jobs WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
        self.db.execute("DELETE FROM meeting_source_clock WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM meeting_deliveries WHERE session_id=?", (sid,))
        self.db.commit()
        self.record("stt.session_deleted", session_id=sid)

    def meeting_subscription(self, sid):
        row = self.db.execute("SELECT data FROM meeting_subscriptions WHERE session_id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def meeting_subscriptions(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT data FROM meeting_subscriptions ORDER BY rowid")]

    def save_meeting_subscription(self, subscription):
        self.db.execute(
            "INSERT INTO meeting_subscriptions VALUES(?,?) "
            "ON CONFLICT(session_id) DO UPDATE SET data=excluded.data",
            (subscription["session_id"], json.dumps(subscription)),
        )
        self.db.commit()

    def forget_meeting_subscription(self, sid):
        self.db.execute("DELETE FROM meeting_subscriptions WHERE session_id=?", (sid,))
        self.db.execute("DELETE FROM meeting_deliveries WHERE session_id=?", (sid,))
        self.db.commit()

    def meeting_arrival(self, sid, utterance_id, revision):
        row = self.db.execute(
            "SELECT received_at FROM meeting_source_clock WHERE session_id=? AND utterance_id=? AND revision=?",
            (sid, utterance_id, revision),
        ).fetchone()
        return row[0] if row else None

    def meeting_delivery(self, sid, source_key, received_at):
        self.db.execute("INSERT OR IGNORE INTO meeting_deliveries VALUES(?,?,?,0)",
                        (sid, source_key, received_at))
        self.db.commit()
        row = self.db.execute("SELECT received_at,delivered FROM meeting_deliveries "
                              "WHERE session_id=? AND source_key=?", (sid, source_key)).fetchone()
        return {"received_at": row[0], "delivered": bool(row[1])}

    def acknowledge_meeting_delivery(self, sid, source_key):
        self.db.execute("UPDATE meeting_deliveries SET delivered=1 WHERE session_id=? AND source_key=?",
                        (sid, source_key))
        self.db.commit()
