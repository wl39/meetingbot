"""Durable STT-to-RAG delivery, independent of browser and microphone connections.

Committed STT snapshots are the inbox; delivery receipts are only acknowledged after
RAG accepts an idempotent source key. Reconciliation repairs a crash at either side
without retaining browser cookies or bearer keys.
"""

import asyncio
import hashlib
import json
import time
from urllib.parse import quote, urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.access import require_owner

router = APIRouter()
STABLE = {"stable", "corrected", "final"}
UTTERANCE_FIELDS = ("utterance_id", "revision", "text", "status", "speaker_id", "start_ms", "end_ms")


class SubscriptionInput(BaseModel):
    workspace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    enabled: bool


class RetryInput(BaseModel):
    workspace_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def source_hash(source):
    return hashlib.sha256(
        json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def source_entries(session, subscription, legacy_receipts=()):
    """Use only current, committed speech; client text and context are never trusted."""
    utterances = sorted(
        (u for u in session["utterances"] if u["status"] in STABLE and u["text"].strip()),
        key=lambda u: (u["start_ms"], u["end_ms"], u["utterance_id"]),
    )
    for index, utterance in enumerate(utterances):
        before, after = utterances[max(0, index - 3):index], utterances[index + 1:index + 3]

        def context(items):
            # Preserve complete speech; the classifier applies its own bounded whole-
            # utterance window and explicitly reports omitted context.
            return [{"text": u["text"], "speaker_id": u.get("speaker_id"),
                     "utterance_id": u["utterance_id"], "revision": u["revision"]} for u in items]

        payload = {
            "session_id": session["id"],
            "utterance": {key: utterance.get(key) for key in UTTERANCE_FIELDS},
            "context": context(before), "following_context": context(after),
            "revision_id": subscription.get("resolved_revision_id") or subscription.get("revision_id"),
            "origin": "file" if session["mode"] == "file" else "live",
            "addressed_to_ai": bool(utterance.get("addressed_to_ai", False)),
        }
        # RAG treats manual corrections as stable input; source revision still fences old results.
        if payload["utterance"]["status"] == "corrected":
            payload["utterance"]["status"] = "stable"
        source = {**payload, "subscription_generation": subscription.get("generation", 1)}
        legacy_key = source_hash(source)
        # STT revisions also advance for finalization/metadata. Only changed speech,
        # speakers, timing, context or corpus should restart an otherwise valid analysis.
        semantic = {**source,
                    "utterance": {k: v for k, v in source["utterance"].items() if k != "revision"},
                    "context": [{k: v for k, v in u.items() if k != "revision"} for u in source["context"]],
                    "following_context": [{k: v for k, v in u.items() if k != "revision"}
                                          for u in source["following_context"]]}
        semantic["utterance"]["status"] = "stable"
        signature = source_hash(semantic)
        previous = subscription.get("source_states", {}).get(utterance["utterance_id"])
        if previous and previous["signature"] == signature and previous["active"]:
            key = previous["source_key"]
        elif previous:
            # A -> B -> A and a retracted/reinserted utterance need a new incarnation;
            # the original A was superseded upstream and its receipt cannot be reused.
            key = source_hash({"signature": signature, "previous": previous["source_key"],
                               "generation": session.get("snapshot_revision", 1)})
        else:
            # Upgrade existing receipts in place, including accepted-but-unacknowledged
            # requests, so a deployment cannot replay every completed recording.
            key = legacy_key if legacy_key in legacy_receipts else signature
        payload["source_key"] = key
        # A monotonic transport guard, independent of per-utterance idempotency: unrelated
        # snapshot changes must not cause every historical utterance to run again.
        payload["source_generation"] = session.get("snapshot_revision", 1)
        yield payload, {"signature": signature, "source_key": key, "active": True}


def source_payloads(session, subscription, legacy_receipts=()):
    for payload, _ in source_entries(session, subscription, legacy_receipts):
        yield payload


def source_receipts(repo, sid):
    return {row[0]: bool(row[1]) for row in repo.db.execute(
        "SELECT source_key,delivered FROM meeting_deliveries WHERE session_id=?", (sid,))}


def public_subscription(subscription):
    return {key: subscription.get(key) if subscription else (False if key == "enabled" else None)
            for key in ("enabled", "workspace_id", "revision_id")}


class SubscriptionDelivery:
    def __init__(self, repo, bridge, access):
        self.repo, self.bridge, self.access = repo, bridge, access
        self.wakeup = asyncio.Event()
        self.locks = {}
        self.gate = asyncio.Semaphore(4)

    def lock(self, sid):
        return self.locks.setdefault(sid, asyncio.Lock())

    async def upstream(self, path, body):
        result = await asyncio.to_thread(self.bridge.request, path, body, subscription=True)
        if isinstance(result, JSONResponse):
            code = json.loads(result.body).get("detail", "RAG_REQUEST_FAILED")
            raise HTTPException(result.status_code, code)
        return result

    async def run(self):
        while True:
            self.wakeup.clear()
            try:
                await self.poll()
            except asyncio.CancelledError:
                raise
            except Exception:
                # The source remains committed. A transient local failure cannot kill delivery.
                self.repo.record("meeting.delivery_failed", code="LOCAL_DELIVERY_ERROR")
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=0.5)
            except TimeoutError:
                pass

    async def poll(self):
        subscriptions = [s for s in self.repo.meeting_subscriptions()
                         if s.get("enabled") or s.get("cleanup_pending") or s.get("pending_cleanup")]
        # Admit live speech before file backfills; all submissions remain persisted on overload.
        subscriptions.sort(key=lambda s: s.get("origin") == "file")
        await asyncio.gather(*(self.deliver(s["session_id"]) for s in subscriptions))

    async def deliver(self, sid):
        async with self.gate, self.lock(sid):
            subscription = self.repo.meeting_subscription(sid)
            if not subscription or subscription.get("next_attempt_at", 0) > time.time():
                return
            try:
                await self._deliver(subscription)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                current = self.repo.meeting_subscription(sid)
                if current:
                    failures = min(current.get("failures", 0) + 1, 8)
                    code = error.detail if isinstance(error, HTTPException) else "RAG_DELIVERY_FAILED"
                    # Only known machine codes are retained, never upstream response internals.
                    if not isinstance(code, str) or not code.replace("_", "").isalnum() or len(code) > 80:
                        code = "RAG_DELIVERY_FAILED"
                    current.update(failures=failures, last_error=code,
                                   next_attempt_at=time.time() + min(2 ** (failures - 1), 30))
                    self.repo.save_meeting_subscription(current)
                    self.repo.record("meeting.delivery_deferred", session_id=sid, code=code)

    async def _deliver(self, subscription):
        sid, wid = subscription["session_id"], subscription["workspace_id"]
        base = f"/workspaces/{wid}/meeting/sessions/{quote(sid, safe='')}"
        session = self.repo.get(sid)
        for previous in list(subscription.get("pending_cleanup", [])):
            await self.upstream(f"/workspaces/{previous}/meeting/sessions/{quote(sid, safe='')}/cancel",
                                {"delete": not session or subscription.get("deleted", False)})
            latest = self.repo.meeting_subscription(sid)
            if latest and latest.get("deleted") and not subscription.get("deleted"):
                self.wakeup.set()
                return
            subscription["pending_cleanup"].remove(previous)
            self.repo.save_meeting_subscription(subscription)
        if not session or subscription.get("cleanup_pending"):
            await self.upstream(base + "/cancel", {"delete": not session or subscription.get("deleted", False)})
            if not session:
                self.repo.forget_meeting_subscription(sid)
            else:
                subscription.update(cleanup_pending=False, failures=0, last_error=None, next_attempt_at=0)
                self.repo.save_meeting_subscription(subscription)
            return
        if not subscription["enabled"]:
            return
        receipts = source_receipts(self.repo, sid)
        entries = list(source_entries(session, subscription, receipts))
        payloads = [payload for payload, _ in entries]
        states = {uid: {**state, "active": False}
                  for uid, state in subscription.get("source_states", {}).items()}
        states.update({payload["utterance"]["utterance_id"]: state for payload, state in entries})
        if subscription.get("source_states") != states:
            subscription["source_states"] = states
            # Persist identity before any external call. A crash/retry must retain the
            # same incarnation even when context changes while admission is in flight.
            self.repo.save_meeting_subscription(subscription)
        # A split, merge or deletion must invalidate obsolete accepted work, including completed results.
        generation = session.get("snapshot_revision", 1)
        if subscription.get("synced_generation") != generation:
            await self.upstream(base + "/sync", {"utterance_ids": [p["utterance"]["utterance_id"] for p in payloads],
                                                "generation": generation})
            subscription["synced_generation"] = generation
            subscription["synced_at"] = time.time()
        delivered = {key for key, acknowledged in receipts.items() if acknowledged}
        admitted = 0
        for payload in payloads:
            if payload["source_key"] in delivered:
                continue
            # Never forward a snapshot that changed while sync/admission was in flight.
            current = self.repo.get(sid)
            if not current or current.get("snapshot_revision") != generation:
                self.wakeup.set()
                return
            utterance = payload["utterance"]
            arrival = self.repo.meeting_arrival(sid, utterance["utterance_id"], utterance["revision"])
            # File playback is admitted gradually; its queue clock starts on admission.
            received_at = (max(arrival or 0, subscription.get("enabled_at", 0))
                           if payload["origin"] == "live" else time.time())
            receipt = self.repo.meeting_delivery(sid, payload["source_key"], received_at or time.time())
            payload["received_at"] = receipt["received_at"]
            await self.upstream(f"/workspaces/{wid}/meeting/jobs", payload)
            # A crash before this acknowledgement only resends the same idempotency key.
            self.repo.acknowledge_meeting_delivery(sid, payload["source_key"])
            admitted += 1
            if admitted >= (4 if session["mode"] == "file" else 12):
                break
        # A concurrent transcript deletion marks a tombstone; never overwrite it with an old grant.
        current = self.repo.meeting_subscription(sid)
        if current and not current.get("deleted"):
            subscription.update(failures=0, last_error=None, next_attempt_at=0)
            self.repo.save_meeting_subscription(subscription)


def owned_session(request, sid):
    require_owner(request.app, request.state.principal, sid)
    session = request.app.state.service.repo.get(sid)
    if not session:
        raise HTTPException(404, "SESSION_NOT_FOUND")
    return session


@router.get("/sessions/{sid}/subscription")
async def subscription_status(sid: str, request: Request):
    owned_session(request, sid)
    return public_subscription(request.app.state.service.repo.meeting_subscription(sid))


@router.put("/sessions/{sid}/subscription")
async def subscribe(sid: str, body: SubscriptionInput, request: Request):
    from .router import caller_headers

    session = owned_session(request, sid)
    delivery = request.app.state.meeting_delivery
    repo = request.app.state.service.repo
    async with delivery.lock(sid):
        previous = repo.meeting_subscription(sid)
        if not body.enabled:
            if not previous:
                return {"enabled": False, "workspace_id": body.workspace_id, "revision_id": body.revision_id}
            previous.update(enabled=False, cleanup_pending=True, next_attempt_at=0)
            repo.save_meeting_subscription(previous)
            delivery.wakeup.set()
            return public_subscription(previous)
        same = previous and previous.get("enabled") and previous["workspace_id"] == body.workspace_id and \
            previous.get("revision_id") == body.revision_id
        # Verify and register the grant using the real caller, before any service credential work.
        result = await asyncio.to_thread(
            request.app.state.rag_bridge.request,
            f"/workspaces/{body.workspace_id}/meeting/sessions/{quote(sid, safe='')}/subscription",
            {"enabled": True, "revision_id": body.revision_id}, caller_headers=caller_headers(request),
        )
        if isinstance(result, JSONResponse):
            return result
        subscription = {
            "session_id": sid, "workspace_id": body.workspace_id, "revision_id": body.revision_id,
            "enabled": True, "subject": request.state.principal.subject,
            "generation": (previous or {}).get("generation", 0) + (0 if same else 1),
            "enabled_at": previous["enabled_at"] if same else time.time(),
            "origin": "file" if session["mode"] == "file" else "live",
            "policy_version": result.get("policy_version") if isinstance(result, dict) else None,
            "resolved_revision_id": result.get("revision_id") if isinstance(result, dict) else body.revision_id,
            "workspaces": sorted(set((previous or {}).get("workspaces", []) + [body.workspace_id])),
            "pending_cleanup": (previous or {}).get("pending_cleanup", []),
            "source_states": (previous or {}).get("source_states", {}),
        }
        if previous and previous["workspace_id"] != body.workspace_id:
            subscription["pending_cleanup"] = sorted(set(subscription["pending_cleanup"] +
                                                         [previous["workspace_id"]]))
        # Rapid A -> B -> A changes can leave A in the deferred cleanup list. The
        # newly verified active grant must never be cancelled by an older switch.
        subscription["pending_cleanup"] = [wid for wid in subscription["pending_cleanup"]
                                            if wid != body.workspace_id]
        if not repo.get(sid):
            subscription.update(enabled=False, deleted=True, cleanup_pending=True)
        repo.save_meeting_subscription(subscription)
        delivery.wakeup.set()
        return public_subscription(subscription)


@router.get("/sessions/{sid}/jobs")
async def jobs(sid: str, request: Request, workspace_id: str = Query(pattern=r"^[a-f0-9]{32}$"),
               limit: int = Query(default=15, ge=1, le=50),
               cursor: str | None = Query(default=None, max_length=128),
               include_anchor: bool = Query(default=False)):
    from .router import caller_headers

    owned_session(request, sid)
    query = {"session_id": sid, "limit": limit}
    if cursor is not None:
        query["cursor"] = cursor
    if include_anchor:
        query["include_anchor"] = "true"
    result = await asyncio.to_thread(
        request.app.state.rag_bridge.request,
        f"/workspaces/{workspace_id}/meeting/jobs?{urlencode(query)}",
        caller_headers=caller_headers(request),
    )
    if isinstance(result, JSONResponse):
        return result
    # A result racing a local correction is not allowed to reappear during the next poll gap.
    session = owned_session(request, sid)
    subscription = request.app.state.service.repo.meeting_subscription(sid)
    if subscription and subscription["workspace_id"] == workspace_id:
        receipts = source_receipts(request.app.state.service.repo, sid)
        valid = {p["source_key"] for p in source_payloads(session, subscription, receipts)}

        def current(row):
            return not row.get("source_key") or row["source_key"] in valid

        if isinstance(result, list):
            result = [row for row in result if current(row)]
        elif isinstance(result, dict) and isinstance(result.get("jobs"), list):
            result = {**result, "jobs": [row for row in result["jobs"] if current(row)]}
    return result


@router.post("/sessions/{sid}/jobs/{jid}/retry")
async def retry(sid: str, jid: str, body: RetryInput, request: Request):
    from .router import caller_headers

    owned_session(request, sid)
    if len(jid) > 100 or not jid.replace("_", "").isalnum():
        raise HTTPException(422, "INVALID_JOB")
    return await asyncio.to_thread(
        request.app.state.rag_bridge.request,
        f"/workspaces/{body.workspace_id}/meeting/jobs/{quote(jid, safe='')}/retry",
        {"session_id": sid}, caller_headers=caller_headers(request),
    )
