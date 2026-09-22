"""Bounded, consent-gated STT -> extraction -> local RAG -> grounded popup pipeline."""

import hashlib
import json
import math
import re
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .answers import classify
from .db import dumps, uid
from .prompt_policy import writing_prompt
from .settings import ROOT
from .sources import RagError
from .workspace_guides import guide_provenance, guide_reference

COLORS = {"warning": "red", "caution": "orange", "info": "blue", "success": "green"}
TOTAL_SECONDS = 35


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MeetingUtterance(StrictModel):
    utterance_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=10000)
    status: Literal["stable", "final"]
    speaker_id: str | None = Field(default=None, max_length=128)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @field_validator("text", "utterance_id")
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError("Value cannot be blank")
        return value

    @model_validator(mode="after")
    def ordered_time(self):
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms must be at least start_ms")
        return self


class MeetingContext(StrictModel):
    text: str = Field(min_length=1, max_length=10000)
    speaker_id: str | None = Field(default=None, max_length=128)


class MeetingInput(StrictModel):
    session_id: str = Field(min_length=1, max_length=128)
    utterance: MeetingUtterance
    context: list[MeetingContext] = Field(default_factory=list, max_length=3)
    revision_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")


class Extraction(StrictModel):
    relevant: bool
    keywords: list[str] = Field(max_length=8)
    query: str = Field(max_length=400)
    intent: Literal["fact_check", "practical_guidance", "context", "none"]
    claim: str = Field(max_length=2000)

    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, values):
        if any(not word.strip() or len(word) > 60 for word in values):
            raise ValueError("Invalid keyword")
        return list(dict.fromkeys(word.strip() for word in values))

    @model_validator(mode="after")
    def coherent(self):
        if self.relevant and (not self.query.strip() or not self.keywords or self.intent == "none"):
            raise ValueError("Relevant extraction needs a query and keywords")
        if self.intent == "fact_check" and not self.claim.strip():
            raise ValueError("Fact check needs a claim")
        return self


class SupportQuote(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    quote: str = Field(min_length=8, max_length=2000)


class PopupOutput(StrictModel):
    status: Literal["popup", "suppressed", "insufficient_evidence"]
    assessment: Literal["contradicted", "supported", "supplemental", "conflicting", "uncertain", "irrelevant"]
    scope_match: bool
    kind: Literal["warning", "caution", "info", "success"]
    title: str = Field(max_length=80)
    message: str = Field(max_length=800)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    citations: list[str] = Field(max_length=6)
    support_quotes: list[SupportQuote] = Field(max_length=12)


def parse_output(content, schema):
    try:
        if not isinstance(content, str) or len(content) > 16000:
            raise ValueError("Invalid response size")
        return schema.model_validate(json.loads(content))
    except (ValueError, TypeError, ValidationError):
        raise RagError("INVALID_MEETING_LLM_OUTPUT") from None


def normalized(text):
    return re.sub(r"\s+", " ", text).strip()


def validate_popup(output, evidence, analysis):
    if output.status != "popup":
        return (
            output.status,
            None,
            "NO_RELEVANT_INFORMATION" if output.status == "suppressed" else "NO_SUPPORT",
        )
    sources = {e["evidence_id"]: e["text"] for e in evidence}
    citations = list(dict.fromkeys(output.citations))
    quoted = set()
    for quote in output.support_quotes:
        if quote.evidence_id not in sources or normalized(quote.quote) not in normalized(
            sources[quote.evidence_id]
        ):
            raise RagError("INVALID_LLM_CITATIONS")
        quoted.add(quote.evidence_id)
    if not citations or not set(citations) <= sources.keys() or not set(citations) <= quoted:
        raise RagError("INVALID_LLM_CITATIONS")
    if not output.title.strip() or not output.message.strip():
        raise RagError("INVALID_MEETING_LLM_OUTPUT")
    if output.confidence < 0.65 or output.assessment == "irrelevant":
        return "insufficient_evidence", None, "LOW_CONFIDENCE"
    if output.assessment == "conflicting" and len(citations) < 2:
        return "insufficient_evidence", None, "CONFLICT_NEEDS_BOTH_SOURCES"
    kind, title, message = output.kind, output.title, output.message
    definitive = {"warning": "contradicted", "success": "supported"}
    if kind in definitive and (
        not analysis.claim.strip()
        or not output.scope_match
        or output.assessment != definitive[kind]
        or output.confidence < 0.85
    ):
        # Merely recoloring an unsupported correction would leave its assertion visible.
        kind, title, message = (
            "caution",
            "적용 범위 확인 필요",
            "관련 자료를 찾았지만 발화와 동일한 조건의 사실인지 확인이 필요합니다. 근거에서 환경과 적용 시점을 확인하세요.",
        )
    elif output.assessment in {"conflicting", "uncertain"}:
        kind = "caution"
    if kind == "success" and analysis.intent != "fact_check":
        # Keep supported guidance, but reserve green for explicit fact verification.
        kind = "caution" if analysis.intent == "practical_guidance" else "info"
    return (
        "popup",
        {
            "kind": kind,
            "color": COLORS[kind],
            "title": title,
            "message": message,
            "confidence": output.confidence,
            "citations": citations,
        },
        None,
    )


class MeetingService:
    def __init__(self, core, answer):
        self.c, self.answer = core, answer
        self.extract_prompt = (ROOT / "prompts/meeting_extract.md").read_text(encoding="utf-8")
        self.popup_prompt = (ROOT / "prompts/meeting_popup.md").read_text(encoding="utf-8")

    def approved_config(self, wid, expected=None):
        with self.c.workspaces.locks[wid], self.c.db.transaction():
            ws = self.c.workspaces.get(wid)
            config, version = self.answer.settings.snapshot()
            if not config.enabled or ws["consent"] != self.answer.settings.provider_id(config):
                raise RagError("EXTERNAL_LLM_NOT_APPROVED")
            if expected is not None and (config, version) != expected:
                raise RagError("SETTINGS_CHANGED")
            if not self.answer.factory.configured(config):
                raise RagError("PROXY_NOT_CONFIGURED")
            return config, version

    def invoke(self, wid, expected, prompt, payload, seconds, deadline, tokens):
        # Approval is checked again for every transmission, including after retrieval.
        config, _ = self.approved_config(wid, expected)
        remaining = deadline - time.monotonic()
        if remaining < 1:
            raise RagError("MEETING_TIMEOUT")
        encoded = dumps(payload)
        if len(prompt) + len(encoded) > config.input_chars:
            raise RagError("LLM_INPUT_LIMIT")
        bounded = config.model_copy(
            update={
                "timeout_seconds": min(seconds, config.timeout_seconds, remaining),
                "max_output_tokens": min(config.max_output_tokens, tokens),
            }
        )
        llm = self.answer.factory.create(bounded)
        return llm.invoke([("system", prompt), ("user", encoded)]).content

    @staticmethod
    def classified_result(wid, body, analysis):
        return {
            "workspace_id": wid,
            "session_id": body.session_id,
            "utterance_id": body.utterance.utterance_id,
            "utterance_revision": body.utterance.revision,
            "revision_id": body.revision_id,
            "request_id": uid(),
            "status": "unavailable",
            "popup": None,
            "evidence": [],
            "analysis": analysis.model_dump(exclude={"relevant"}),
            "timings_ms": {"extraction": 0, "query_embedding": 0, "retrieval": 0, "generation": 0},
        }

    @staticmethod
    def checkpoint_hash(value):
        return hashlib.sha256(dumps(value).encode()).hexdigest()

    def retrieve_classified(self, wid, body: MeetingInput, analysis: Extraction) -> dict:
        """Prepare a serializable retrieval checkpoint; the scheduler owns its execution slot."""
        started = time.monotonic()
        result = self.classified_result(wid, body, analysis)
        try:
            expected = self.approved_config(wid)
            config, version = expected
            with self.c.workspaces.locks[wid]:
                _, revision = self.c.revisions.resolve(wid, body.revision_id)
                result["revision_id"] = revision["id"]
            if not analysis.relevant:
                result.update(status="suppressed", reason="NO_RELEVANT_INFORMATION")
                return result
            retrieved = self.c.retrieval.search(wid, analysis.query, result["revision_id"], top_k=6)
            result["evidence"] = retrieved["evidence"]
            result["timings_ms"].update(retrieved["timings_ms"])
            self.approved_config(wid, expected)
            with self.c.workspaces.locks[wid]:
                self.c.revisions.resolve(wid, result["revision_id"])
            result["checkpoint"] = {
                "settings_version": version,
                "settings_hash": self.checkpoint_hash(config.model_dump()),
                "revision_id": result["revision_id"],
                "input_hash": self.checkpoint_hash([body.model_dump(), analysis.model_dump()]),
                "evidence_hash": self.checkpoint_hash(result["evidence"]),
                "access_scope_version": retrieved.get("access_scope_version"),
            }
            if not result["evidence"]:
                result.update(status="insufficient_evidence", reason="NO_EVIDENCE")
            else:
                result["status"] = "ready_for_generation"
        except Exception as error:
            result.update(status="unavailable", reason=classify(error), popup=None, evidence=[])
        finally:
            result["timings_ms"]["total"] = round((time.monotonic() - started) * 1000)
        return result

    def generate_classified(
        self,
        wid,
        body: MeetingInput,
        analysis: Extraction,
        prepared: dict,
        timeout_seconds: float = 20,
    ) -> dict:
        """Resume a retrieved job with fresh access checks and grounded output validation."""
        started = time.monotonic()
        deadline = started + timeout_seconds
        result = self.classified_result(wid, body, analysis)
        previous_ms = 0
        try:
            if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
                raise RagError("MEETING_TIMEOUT")
            expected = self.approved_config(wid)
            config, version = expected
            checkpoint = prepared.get("checkpoint", {})
            if (
                prepared.get("workspace_id") != wid
                or prepared.get("session_id") != body.session_id
                or prepared.get("utterance_id") != body.utterance.utterance_id
                or prepared.get("utterance_revision") != body.utterance.revision
                or prepared.get("analysis") != analysis.model_dump(exclude={"relevant"})
                or prepared.get("revision_id") != checkpoint.get("revision_id")
                or body.revision_id not in {None, prepared.get("revision_id")}
                or checkpoint.get("input_hash")
                != self.checkpoint_hash([body.model_dump(), analysis.model_dump()])
                or checkpoint.get("evidence_hash") != self.checkpoint_hash(prepared.get("evidence", []))
                or prepared.get("status") != "ready_for_generation"
            ):
                raise RagError("INVALID_MEETING_CHECKPOINT")
            if checkpoint.get("settings_version") != version or checkpoint.get(
                "settings_hash"
            ) != self.checkpoint_hash(config.model_dump()):
                raise RagError("SETTINGS_CHANGED")
            # Copy a persisted checkpoint so a failed attempt cannot corrupt the resumable job.
            result = json.loads(dumps(prepared))
            previous_ms = result["timings_ms"].get("total", 0)
            result.pop("reason", None)
            with self.c.workspaces.locks[wid]:
                self.c.revisions.resolve(wid, result["revision_id"])
                _, access_version = self.c.sources.roots()
                if checkpoint.get("access_scope_version") not in {None, access_version}:
                    raise RagError("SOURCE_POLICY_CHANGED")
                guide = self.c.guides.get(wid)
                operating = self.answer.prompts.active()
            if not result["evidence"]:
                result.update(status="insufficient_evidence", reason="NO_EVIDENCE")
                return result
            payload = {
                "utterance": body.utterance.model_dump(),
                "context": [item.model_dump() for item in body.context],
                "analysis": result["analysis"],
                "evidence": [
                    {"evidence_id": e["evidence_id"], "text": e["text"]} for e in result["evidence"]
                ],
                **guide_reference(guide),
            }
            prompt = writing_prompt(operating["content"], "[회의 검토 출력 계약]\n" + self.popup_prompt)
            result["guidance"] = guide_provenance(guide)
            result["operating_prompt"] = {
                "id": operating["id"],
                "version": operating["sequence"],
                "content_hash": operating["content_hash"],
            }
            stage = time.monotonic()
            try:
                output = parse_output(
                    self.invoke(wid, expected, prompt, payload, timeout_seconds, deadline, 1800), PopupOutput
                )
            finally:
                result["timings_ms"]["generation"] = round((time.monotonic() - stage) * 1000)
            if time.monotonic() > deadline:
                raise RagError("MEETING_TIMEOUT")
            self.approved_config(wid, expected)
            with self.c.workspaces.locks[wid]:
                self.c.revisions.resolve(wid, result["revision_id"])
                _, current_access = self.c.sources.roots()
                if checkpoint.get("access_scope_version") not in {None, current_access}:
                    raise RagError("SOURCE_POLICY_CHANGED")
            status, popup, reason = validate_popup(output, result["evidence"], analysis)
            result.update(status=status, popup=popup)
            if reason:
                result["reason"] = reason
            if popup:
                popup["id"] = hashlib.sha256(
                    dumps([wid, body.session_id, body.utterance.utterance_id]).encode()
                ).hexdigest()[:32]
        except Exception as error:
            result.update(status="unavailable", reason=classify(error), popup=None, evidence=[])
        finally:
            result.pop("checkpoint", None)
            result["timings_ms"]["total"] = previous_ms + round((time.monotonic() - started) * 1000)
        return result

    def analyze(self, wid, body):
        started = time.monotonic()
        deadline = started + TOTAL_SECONDS
        # Resolve an authorized immutable source version before sending any transcript.
        with self.c.workspaces.locks[wid]:
            self.c.workspaces.get(wid)
        result = {
            "workspace_id": wid,
            "session_id": body.session_id,
            "utterance_id": body.utterance.utterance_id,
            "utterance_revision": body.utterance.revision,
            "revision_id": body.revision_id,
            "request_id": uid(),
            "status": "unavailable",
            "popup": None,
            "evidence": [],
            "timings_ms": {"extraction": 0, "query_embedding": 0, "retrieval": 0, "generation": 0},
        }
        acquired = False
        try:
            expected = self.approved_config(wid)
            with self.c.workspaces.locks[wid]:
                _, revision = self.c.revisions.resolve(wid, body.revision_id)
                result["revision_id"] = revision["id"]
                guide = self.c.guides.get(wid)
                operating = self.answer.prompts.active()
            acquired = self.answer.factory.gate.acquire(blocking=False)
            if not acquired:
                raise RagError("LLM_BUSY")
            payload = {
                "utterance": body.utterance.model_dump(),
                "context": [item.model_dump() for item in body.context],
            }
            stage = time.monotonic()
            try:
                analysis = parse_output(
                    self.invoke(wid, expected, self.extract_prompt, payload, 12, deadline, 800), Extraction
                )
            finally:
                result["timings_ms"]["extraction"] = round((time.monotonic() - stage) * 1000)
            result["analysis"] = analysis.model_dump(exclude={"relevant"})
            if not analysis.relevant:
                result.update(status="suppressed", reason="NO_RELEVANT_INFORMATION")
                return result
            self.approved_config(wid, expected)
            if time.monotonic() >= deadline:
                raise RagError("MEETING_TIMEOUT")
            retrieved = self.c.retrieval.search(wid, analysis.query, result["revision_id"], top_k=6)
            result["evidence"] = retrieved["evidence"]
            result["timings_ms"].update(retrieved["timings_ms"])
            if not result["evidence"]:
                result.update(status="insufficient_evidence", reason="NO_EVIDENCE")
                return result
            payload.update(
                analysis=result["analysis"],
                evidence=[{"evidence_id": e["evidence_id"], "text": e["text"]} for e in result["evidence"]],
                **guide_reference(guide),
            )
            # Only the writing stage receives preferences, never extraction or retrieval.
            prompt = writing_prompt(operating["content"], "[회의 검토 출력 계약]\n" + self.popup_prompt)
            result["guidance"] = guide_provenance(guide)
            result["operating_prompt"] = {
                "id": operating["id"],
                "version": operating["sequence"],
                "content_hash": operating["content_hash"],
            }
            stage = time.monotonic()
            try:
                output = parse_output(
                    self.invoke(wid, expected, prompt, payload, 20, deadline, 1800), PopupOutput
                )
            finally:
                result["timings_ms"]["generation"] = round((time.monotonic() - stage) * 1000)
            if time.monotonic() > deadline:
                raise RagError("MEETING_TIMEOUT")
            # A revoked source or consent must not yield a late popup after generation.
            self.approved_config(wid, expected)
            with self.c.workspaces.locks[wid]:
                self.c.revisions.resolve(wid, result["revision_id"])
            status, popup, reason = validate_popup(output, result["evidence"], analysis)
            result.update(status=status, popup=popup)
            if reason:
                result["reason"] = reason
            if popup:
                popup["id"] = hashlib.sha256(
                    dumps([wid, body.session_id, body.utterance.utterance_id]).encode()
                ).hexdigest()[:32]
        except Exception as error:
            result.update(status="unavailable", reason=classify(error), popup=None)
            # Source/policy revocation must not return excerpts obtained before revocation.
            result["evidence"] = []
        finally:
            if acquired:
                self.answer.factory.gate.release()
            result["timings_ms"]["total"] = round((time.monotonic() - started) * 1000)
        return result
