"""Bounded, consent-gated importance classification without a shared RAG slot."""

import math
import re
import time
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .db import dumps
from .meeting import Extraction, MeetingInput, MeetingService, StrictModel, parse_output
from .settings import ROOT
from .sources import RagError

CONTEXT_CHARS = 1500
FOLLOWING_CHARS = 1000
SCOPE_CHARS = 1600


class ClassificationOutput(StrictModel):
    score: int | None = Field(ge=1, le=5)
    classification_state: Literal["resolved", "needs_clarification"]
    scope: Literal["in_scope", "out_of_scope", "uncertain"]
    speech_act: Literal["filler", "social", "topic", "factual_claim", "question", "request"]
    addressed_to_ai: bool
    intent: Literal["fact_check", "practical_guidance", "context", "none"]
    keywords: list[str] = Field(max_length=8)
    query: str = Field(max_length=400)
    claim: str = Field(max_length=2000)
    reason_code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z][A-Z0-9_]*$")
    action_supported: bool

    @field_validator("keywords")
    @classmethod
    def valid_keywords(cls, values):
        return Extraction.valid_keywords(values)

    @model_validator(mode="after")
    def coherent(self):
        if self.classification_state == "needs_clarification":
            if self.score is not None or self.scope != "uncertain":
                raise ValueError("Unresolved scope requires an unresolved score")
        elif self.score is None or self.scope == "uncertain":
            raise ValueError("Resolved classification needs a known score and scope")
        if self.score is not None:
            if self.score >= 3 and self.scope != "in_scope":
                raise ValueError("RAG candidates must be in scope")
            if self.score <= 2 and self.scope != "out_of_scope":
                raise ValueError("Low scores require an out-of-scope result")
            if self.score == 1 and self.speech_act != "filler":
                raise ValueError("Only an independent filler has score one")
            if self.score == 3 and self.speech_act != "topic":
                raise ValueError("Score three is a topic introduction")
            if self.score >= 4 and self.speech_act not in {"factual_claim", "question", "request"}:
                raise ValueError("Priority work needs a concrete speech act")
            if self.score == 5 and (not self.addressed_to_ai or self.speech_act != "request"):
                raise ValueError("Score five requires an AI-directed request")
        relevant = self.score is not None and self.score >= 3
        Extraction(
            relevant=relevant, keywords=self.keywords, query=self.query, intent=self.intent, claim=self.claim
        )
        if not relevant and (self.intent != "none" or self.query or self.claim or self.keywords):
            raise ValueError("Low and unresolved scores must not launch retrieval")
        if self.score == 3 and self.intent != "context":
            raise ValueError("Topic introductions need context")
        if self.speech_act in {"question", "request"} and (self.intent == "fact_check" or self.claim):
            raise ValueError("Questions and requests are not asserted facts")
        if relevant and self.speech_act == "factual_claim" and self.intent != "fact_check":
            raise ValueError("Factual claims need fact-check intent")
        return self

    def extraction(self) -> Extraction:
        return Extraction(
            relevant=self.score is not None and self.score >= 3,
            keywords=self.keywords,
            query=self.query,
            intent=self.intent,
            claim=self.claim,
        )


class Classification(ClassificationOutput):
    # Server-set provenance; these fields never come from a model response.
    model: str = ""
    settings_version: int = 0
    context_omitted: bool = False
    timings_ms: dict[str, int] = Field(default_factory=dict)


def explicit_ai_recipient(text: str) -> bool:
    """Conservative evidence for direct invocation; quoted/reported commands do not count."""
    if re.search(r"(?:라고|라는|라며|이라고)\s*(?:말|했|하|요청|적|써|쓰|묻)", text):
        return False
    return bool(
        re.match(
            r"^\s*(?:(?:어|음)[,.，… ]+)?(?:AI야|AI님|에이아이야|에이아이님|회의봇아|회의봇야|"
            r"회의봇|챗지피티야|챗지피티|meetingbot)(?:\s|[,，:!?]|$)",
            text,
            re.IGNORECASE,
        )
    )


def bounded_context(items: list, max_items: int, max_chars: int) -> tuple[list[dict], bool]:
    """Keep complete recent utterances, never truncate a negation, number or target."""
    chosen, used = [], 0
    for item in reversed(items[-max_items:]):
        data = item.model_dump() if hasattr(item, "model_dump") else item
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise RagError("INVALID_MEETING_CONTEXT")
        text = data["text"]
        if not text.strip():
            continue
        if used + len(text) > max_chars:
            # Preserve a contiguous recent window; no misleading gap around a scope correction.
            break
        entry = {"text": text, "speaker_id": data.get("speaker_id")}
        if data.get("utterance_id"):
            entry["utterance_id"] = data["utterance_id"]
        chosen.append(entry)
        used += len(text)
    chosen.reverse()
    return chosen, len(chosen) != len(items)


class MeetingClassifier:
    def __init__(self, core, answer):
        self.c, self.answer = core, answer
        self.meeting = MeetingService(core, answer)
        self.prompt = (ROOT / "prompts/meeting_classify.md").read_text(encoding="utf-8")

    def classify(
        self,
        wid,
        body: MeetingInput,
        *,
        scope: dict,
        model: str,
        following: list[dict] | None = None,
        addressed_to_ai: bool = False,
        timeout_seconds: float = 4,
    ) -> Classification:
        started = time.monotonic()
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise RagError("MEETING_TIMEOUT")
        expected = self.meeting.approved_config(wid)
        config, version = expected
        if not isinstance(scope, dict) or len(dumps(scope)) > SCOPE_CHARS:
            # A clipped exclusion or business target could silently change routing.
            raise RagError("MEETING_SCOPE_LIMIT")
        chosen = model.strip() or config.default_model
        if len(chosen) > 200 or any(ord(char) < 32 or ord(char) == 127 for char in chosen):
            raise RagError("INVALID_LLM_SETTINGS")
        context, prior_omitted = bounded_context(body.context, 3, CONTEXT_CHARS)
        after, after_omitted = bounded_context(following or [], 2, FOLLOWING_CHARS)
        verified_recipient = bool(addressed_to_ai) or explicit_ai_recipient(body.utterance.text)
        payload = {
            "utterance": body.utterance.model_dump(),
            "context": context,
            "following": after,
            "scope_profile": scope,
            "context_omitted": prior_omitted or after_omitted,
            "verified_ai_recipient": verified_recipient,
        }
        encoded = dumps(payload)
        if len(self.prompt) + len(encoded) > config.input_chars:
            raise RagError("LLM_INPUT_LIMIT")
        self.meeting.approved_config(wid, expected)
        remaining = timeout_seconds - (time.monotonic() - started)
        if remaining <= 0:
            raise RagError("MEETING_TIMEOUT")
        bounded = config.model_copy(
            update={
                "default_model": chosen,
                "timeout_seconds": min(config.timeout_seconds, remaining),
                "max_output_tokens": min(config.max_output_tokens, 600),
                # Classification must not inherit an expensive answer-writing effort.
                # None preserves compatibility with non-reasoning providers.
                "reasoning_effort": "low" if config.reasoning_effort is not None else None,
            }
        )
        # The scheduler reserves both a classifier lane and a global LLM slot.
        response = self.answer.factory.create(bounded).invoke([("system", self.prompt), ("user", encoded)])
        if time.monotonic() - started > timeout_seconds:
            raise RagError("MEETING_TIMEOUT")
        self.meeting.approved_config(wid, expected)
        parsed = parse_output(response.content, ClassificationOutput)
        values = parsed.model_dump()
        values["addressed_to_ai"] = verified_recipient
        if parsed.score == 5 and not verified_recipient:
            values.update(score=4, reason_code="AI_RECIPIENT_UNVERIFIED")
        elif parsed.score == 4 and parsed.speech_act == "request" and verified_recipient:
            values.update(score=5)
        # "Unsupported action" means an in-scope execution request, never a
        # filler, unrelated conversation, unresolved scope, or a discussion of an action.
        if values["score"] not in {4, 5} or values["speech_act"] != "request":
            values["action_supported"] = True
            if values["reason_code"] == "UNSUPPORTED_ACTION":
                if values["score"] is None:
                    values["reason_code"] = "SCOPE_UNCERTAIN"
                elif values["score"] <= 2:
                    values["reason_code"] = "LOW_PRIORITY_RECORDED"
                elif values["score"] == 3:
                    values["reason_code"] = "IN_SCOPE_TOPIC"
                elif values["speech_act"] == "factual_claim":
                    values["reason_code"] = "IN_SCOPE_CONCRETE_CLAIM"
                else:
                    values["reason_code"] = "IN_SCOPE_QUESTION"
        return Classification(
            **values,
            model=chosen,
            settings_version=version,
            context_omitted=prior_omitted or after_omitted,
            timings_ms={"classification": round((time.monotonic() - started) * 1000)},
        )
