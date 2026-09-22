"""Classification/routing contracts and resumable RAG stages; no remote model calls."""

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_llm_management import save
from test_meeting import CLAIM, extraction, model, popup, ready, request

from meetingbot_rag.meeting import Extraction, MeetingInput, MeetingService
from meetingbot_rag.meeting_classifier import (
    ClassificationOutput,
    MeetingClassifier,
    explicit_ai_recipient,
)
from meetingbot_rag.sources import RagError

SCOPE = {
    "description": "우리 서비스의 운영서버와 배포 정책",
    "included_topics": ["로그", "배포", "Docker 이미지"],
    "excluded_topics": ["개인 프로젝트", "날씨", "점심"],
    "aliases": ["운영 인프라"],
}


def classified(**updates):
    return {
        "score": 4,
        "classification_state": "resolved",
        "scope": "in_scope",
        "speech_act": "factual_claim",
        "addressed_to_ai": False,
        "intent": "fact_check",
        "keywords": ["운영 로그", "보관 기간"],
        "query": "우리 서비스 운영 로그 보관 기간",
        "claim": CLAIM,
        "reason_code": "IN_SCOPE_CONCRETE_CLAIM",
        "action_supported": True,
        **updates,
    }


def fake_classifier(monkeypatch, c, value=None, callback=None):
    calls, configs = [], []

    class FakeLLM:
        def invoke(self, messages):
            payload = json.loads(messages[1][1])
            calls.append(payload)
            output = callback(payload) if callback else (value or classified())
            return SimpleNamespace(content=output if isinstance(output, str) else json.dumps(output))

    def create(config):
        configs.append(config)
        return FakeLLM()

    monkeypatch.setattr(c.app.state.answer.factory, "create", create)
    return calls, configs


def run_classifier(c, core, wid, body=None, **kwargs):
    return MeetingClassifier(core, c.app.state.answer).classify(
        wid, MeetingInput.model_validate(body or request()), scope=SCOPE, model="cheap-filter", **kwargs
    )


def test_classifier_uses_selected_model_bounded_tokens_and_separate_capacity(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, configs = fake_classifier(monkeypatch, c)
    gate = c.app.state.answer.factory.gate
    gate.acquire()
    try:
        output = run_classifier(c, core, wid)
    finally:
        gate.release()
    assert output.score == 4 and output.extraction().intent == "fact_check"
    assert output.model == "cheap-filter" and output.settings_version > 0
    assert configs[0].default_model == "cheap-filter"
    assert configs[0].max_output_tokens <= 600 and configs[0].timeout_seconds <= 4
    assert calls[0]["scope_profile"] == SCOPE
    assert "guide" not in calls[0] and len(calls) == 1
    assert output.model_dump()["timings_ms"]["classification"] >= 0


def test_empty_filter_model_uses_configured_default(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    _, configs = fake_classifier(monkeypatch, c)
    output = MeetingClassifier(core, c.app.state.answer).classify(
        wid, MeetingInput.model_validate(request()), scope=SCOPE, model=""
    )
    assert output.model == configs[0].default_model == "synthetic-model"


def test_filter_does_not_inherit_high_answer_reasoning_effort(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    save(c, reasoning_effort="high")
    _, configs = fake_classifier(monkeypatch, c)
    run_classifier(c, core, wid)
    assert configs[0].reasoning_effort == "low"
    assert c.app.state.answer.settings.snapshot()[0].reasoning_effort == "high"


@pytest.mark.parametrize("approved", [True, False])
def test_filter_rechecks_consent_after_transmission(client, monkeypatch, approved):
    c, _, core = client
    wid, _ = ready(client, approve=approved)

    def revoke(_):
        core.db.execute("UPDATE workspaces SET consent=NULL WHERE id=?", (wid,))
        return classified()

    calls, _ = fake_classifier(monkeypatch, c, callback=revoke)
    with pytest.raises(RagError, match="EXTERNAL_LLM_NOT_APPROVED"):
        run_classifier(c, core, wid)
    assert len(calls) == int(approved)


def test_filter_does_not_accept_result_after_settings_change(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)

    def change(_):
        save(c, temperature=0.2)
        return classified()

    fake_classifier(monkeypatch, c, callback=change)
    with pytest.raises(RagError, match="SETTINGS_CHANGED"):
        run_classifier(c, core, wid)


@pytest.mark.parametrize(
    "updates",
    [
        {"score": 1, "speech_act": "filler"},
        {"score": 2, "speech_act": "social"},
        {"score": 2, "speech_act": "question"},
        {"score": 2, "speech_act": "request", "addressed_to_ai": True},
    ],
)
def test_low_scores_remain_saved_classifications_without_retrieval(client, monkeypatch, updates):
    c, _, core = client
    wid, _ = ready(client)
    value = classified(scope="out_of_scope", intent="none", keywords=[], query="", claim="", **updates)
    fake_classifier(monkeypatch, c, value)
    monkeypatch.setattr(core.retrieval, "search", lambda *_a, **_k: pytest.fail("No filter search"))
    output = run_classifier(c, core, wid)
    assert output.score == updates["score"] and not output.extraction().relevant


def test_uncertain_is_null_and_topic_is_retrievable():
    pending = ClassificationOutput.model_validate(
        classified(
            score=None,
            classification_state="needs_clarification",
            scope="uncertain",
            speech_act="question",
            intent="none",
            claim="",
            query="",
            keywords=[],
        )
    )
    assert pending.score is None and not pending.extraction().relevant
    topic = ClassificationOutput.model_validate(
        classified(score=3, speech_act="topic", intent="context", claim="")
    )
    assert topic.extraction().relevant and topic.extraction().query


@pytest.mark.parametrize(
    "updates",
    [
        {"score": True},
        {"score": 6},
        {"scope": "out_of_scope"},
        {"score": None},
        {"score": 3},
        {"score": 5},
        {"speech_act": "question"},
        {"claim": ""},
        {"query": ""},
        {"reason_code": "장황한 설명"},
        {"model": "model-chosen-by-response"},
    ],
)
def test_incoherent_or_forged_classifications_are_rejected(updates):
    with pytest.raises(ValidationError):
        ClassificationOutput.model_validate(classified(**updates))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("AI야 운영 로그 보관일 알려줘", True),
        ("회의봇 운영 로그 보관일 알려줘", True),
        ("어, AI야 운영 로그 보관일 알려줘", True),
        ("운영 로그 보관일 알려줘", False),
        ('"AI야 운영 로그 보관일 알려줘"', False),
        ("그가 AI야 운영 로그 보관일 알려줘라고 말했어요", False),
        ("AI야 운영 로그 삭제해라고 말했어요", False),
        ("AI 모델은 어떤 것인가요?", False),
    ],
)
def test_explicit_ai_invocation_needs_nonquoted_server_evidence(text, expected):
    assert explicit_ai_recipient(text) is expected


@pytest.mark.parametrize("verified,expected", [(False, 4), (True, 5)])
def test_model_cannot_invent_ai_recipient(client, monkeypatch, verified, expected):
    c, _, core = client
    wid, _ = ready(client)
    fake_classifier(
        monkeypatch,
        c,
        classified(score=5, speech_act="request", addressed_to_ai=True, intent="context", claim=""),
    )
    output = run_classifier(c, core, wid, request("운영 로그 보관일 알려줘"), addressed_to_ai=verified)
    assert output.score == expected and output.addressed_to_ai is verified


def test_support_flag_does_not_make_an_external_action_executable(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    fake_classifier(
        monkeypatch,
        c,
        classified(
            score=5,
            speech_act="request",
            addressed_to_ai=True,
            intent="context",
            claim="",
            action_supported=False,
            reason_code="UNSUPPORTED_ACTION",
        ),
    )
    output = run_classifier(c, core, wid, request("AI야 우리 운영 로그 삭제해"))
    assert output.score == 5 and output.action_supported is False


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"score": 1, "scope": "out_of_scope", "speech_act": "filler"}, "LOW_PRIORITY_RECORDED"),
        ({"score": 2, "scope": "out_of_scope", "speech_act": "question"}, "LOW_PRIORITY_RECORDED"),
        ({"score": 2, "scope": "out_of_scope", "speech_act": "request"}, "LOW_PRIORITY_RECORDED"),
        (
            {
                "score": None,
                "classification_state": "needs_clarification",
                "scope": "uncertain",
                "speech_act": "request",
            },
            "SCOPE_UNCERTAIN",
        ),
    ],
)
def test_unsupported_action_flag_cannot_replace_low_or_unresolved_classification(
    client, monkeypatch, updates, reason
):
    c, _, core = client
    wid, _ = ready(client)
    value = classified(
        **updates,
        intent="none",
        keywords=[],
        query="",
        claim="",
        action_supported=False,
        reason_code="UNSUPPORTED_ACTION",
    )
    fake_classifier(monkeypatch, c, value)
    output = run_classifier(c, core, wid)
    assert output.score == value["score"] and output.classification_state == value["classification_state"]
    assert output.action_supported is True and output.reason_code == reason
    assert not output.extraction().relevant


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"score": 3, "speech_act": "topic", "intent": "context", "claim": ""}, "IN_SCOPE_TOPIC"),
        ({"speech_act": "question", "intent": "context", "claim": ""}, "IN_SCOPE_QUESTION"),
        ({"speech_act": "factual_claim"}, "IN_SCOPE_CONCRETE_CLAIM"),
    ],
)
def test_unsupported_action_flag_cannot_drop_topics_questions_or_factual_claims(
    client, monkeypatch, updates, reason
):
    c, _, core = client
    wid, _ = ready(client)
    fake_classifier(
        monkeypatch, c, classified(**updates, action_supported=False, reason_code="UNSUPPORTED_ACTION")
    )
    output = run_classifier(c, core, wid)
    assert output.action_supported is True and output.reason_code == reason
    assert output.extraction().relevant


def test_in_scope_execution_request_without_ai_vocative_remains_unsupported(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    fake_classifier(
        monkeypatch,
        c,
        classified(
            score=4,
            speech_act="request",
            intent="context",
            claim="",
            action_supported=False,
            reason_code="UNSUPPORTED_ACTION",
        ),
    )
    output = run_classifier(c, core, wid, request("우리 운영 로그를 삭제해줘"))
    assert output.score == 4 and output.action_supported is False
    assert output.reason_code == "UNSUPPORTED_ACTION"


def test_long_utterance_is_complete_and_context_keeps_whole_recent_items(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = fake_classifier(monkeypatch, c)
    text = "가" * 9000 + " 운영 로그는 45일이 아니에요."
    body = request(
        text,
        context=[{"text": "앞" * 800}, {"text": "중" * 800}, {"text": "개인 프로젝트 내용이에요."}],
    )
    output = run_classifier(c, core, wid, body, following=[{"text": "지금 질문은 우리 서비스 기준이에요."}])
    assert calls[0]["utterance"]["text"] == text
    assert calls[0]["context"] == [
        {"text": "중" * 800, "speaker_id": None},
        {"text": "개인 프로젝트 내용이에요.", "speaker_id": None},
    ]
    assert calls[0]["following"][0]["text"] == "지금 질문은 우리 서비스 기준이에요."
    assert output.context_omitted


def test_oversized_context_is_omitted_whole_without_leaving_an_older_wrong_scope(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    long_context = (
        "우리 서비스 운영 정책을 이야기했어요. " + "설명 " * 1000 + "지금은 개인 프로젝트 얘기예요."
    )
    body = request(
        "그 도커 이미지 관리는 어떻게 해요?",
        context=[{"text": "우리 운영서비스의 도커를 검토합니다."}, {"text": long_context}],
    )
    pending = classified(
        score=None,
        classification_state="needs_clarification",
        scope="uncertain",
        speech_act="question",
        intent="none",
        claim="",
        query="",
        keywords=[],
        reason_code="CONTEXT_OMITTED_TARGET_UNCERTAIN",
    )
    calls, _ = fake_classifier(monkeypatch, c, pending)
    output = run_classifier(c, core, wid, body)
    assert calls[0]["context"] == [] and calls[0]["context_omitted"] is True
    assert output.score is None and output.scope == "uncertain"
    assert not output.extraction().relevant
    # The stored/source input remains complete, including the correction at its end.
    assert body["context"][-1]["text"] == long_context


@pytest.mark.parametrize("score,verified", [(4, False), (5, True), (5, False)])
def test_missing_context_never_demotes_a_resolved_priority_candidate_out_of_pq(
    client, monkeypatch, score, verified
):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = fake_classifier(
        monkeypatch,
        c,
        classified(score=score, speech_act="request", addressed_to_ai=score == 5, intent="context", claim=""),
    )
    body = request(
        "우리 서비스 운영서버의 로그 보관일을 알려줘",
        context=[{"text": "긴 앞 문맥 " * 1000}],
    )
    output = run_classifier(c, core, wid, body, addressed_to_ai=verified)
    assert calls[0]["context"] == [] and output.context_omitted
    assert output.score == (5 if verified else 4) and output.extraction().relevant
    assert output.query and output.intent == "context"


@pytest.mark.parametrize(
    "text,claim,context",
    [
        ("네", "운영서버 접속에 승인이 필요 없다", "운영서버 접속에 승인이 필요 없다는 말씀이죠?"),
        ("어, 우리 운영 로그는 45일이 아니에요", "우리 운영 로그는 45일이 아니다", "로그 정책 검토입니다."),
        ("오늘 덥네요. 우리 운영 로그는 90일이에요", "우리 운영 로그는 90일이다", "로그 정책 검토입니다."),
    ],
)
def test_meaningful_short_filler_prefixed_and_mixed_claims_remain_priority(
    client, monkeypatch, text, claim, context
):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = fake_classifier(monkeypatch, c, classified(claim=claim))
    output = run_classifier(c, core, wid, request(text, context=[{"text": context}]))
    assert len(calls) == 1 and calls[0]["utterance"]["text"] == text
    assert output.score == 4 and output.extraction().claim == claim


def test_oversized_following_context_is_not_sent_as_a_partial_scope_correction(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = fake_classifier(monkeypatch, c)
    following = [{"text": "지금 질문의 대상 설명 " * 300 + "개인 프로젝트를 말한 겁니다."}]
    output = run_classifier(c, core, wid, following=following)
    assert calls[0]["following"] == [] and calls[0]["context_omitted"]
    assert output.context_omitted


def test_filter_input_and_scope_limits_fail_without_transmitting(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = fake_classifier(monkeypatch, c)
    service = MeetingClassifier(core, c.app.state.answer)
    body = MeetingInput.model_validate(request())
    with pytest.raises(RagError, match="MEETING_SCOPE_LIMIT"):
        service.classify(wid, body, scope={"description": "범" * 1601}, model="cheap-filter")
    save(c, input_chars=4000)
    with pytest.raises(RagError, match="LLM_INPUT_LIMIT"):
        run_classifier(c, core, wid, request("가" * 10000))
    assert not calls


def test_classifier_error_does_not_turn_into_score_two(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    fake_classifier(monkeypatch, c, "not json")
    with pytest.raises(RagError, match="INVALID_MEETING_LLM_OUTPUT"):
        run_classifier(c, core, wid)


def test_split_stages_resume_from_json_without_extracting_or_using_global_gate(client, monkeypatch):
    c, _, core = client
    wid, revision = ready(client)
    calls, _ = model(monkeypatch, c)
    service = MeetingService(core, c.app.state.answer)
    body = MeetingInput.model_validate(request())
    analysis = Extraction.model_validate(extraction())
    gate = c.app.state.answer.factory.gate
    gate.acquire()
    try:
        prepared = service.retrieve_classified(wid, body, analysis)
        assert prepared["status"] == "ready_for_generation" and not calls
        assert "synthetic-key" not in json.dumps(prepared)
        output = service.generate_classified(wid, body, analysis, json.loads(json.dumps(prepared)))
    finally:
        gate.release()
    assert output["status"] == "popup" and output["revision_id"] == revision
    assert output["popup"]["color"] == "red" and len(calls) == 1
    assert "checkpoint" not in output and "checkpoint" in prepared


@pytest.mark.parametrize(
    "change", ["consent", "settings", "source", "input", "evidence", "analysis", "revision"]
)
def test_resume_revalidates_checkpoint_before_generation(client, monkeypatch, change):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c)
    service = MeetingService(core, c.app.state.answer)
    body = MeetingInput.model_validate(request())
    analysis = Extraction.model_validate(extraction())
    prepared = service.retrieve_classified(wid, body, analysis)
    if change == "consent":
        core.db.execute("UPDATE workspaces SET consent=NULL WHERE id=?", (wid,))
    elif change == "settings":
        save(c, temperature=0.2)
    elif change == "source":
        core.s.source_roots_file.write_text("roots: []")
    elif change == "input":
        body.utterance.revision += 1
    elif change == "evidence":
        prepared["evidence"][0]["text"] = "바꿔치기한 근거"
    elif change == "analysis":
        prepared["analysis"]["claim"] = "바꿔치기한 주장"
    else:
        prepared["revision_id"] = "a" * 32
    result = service.generate_classified(wid, body, analysis, prepared)
    assert result["status"] == "unavailable" and result["popup"] is None and result["evidence"] == []
    assert not calls


@pytest.mark.parametrize("event", ["consent", "citation"])
def test_resume_checks_late_revocation_and_citations(client, monkeypatch, event):
    c, _, core = client
    wid, _ = ready(client)

    def generate(payload):
        if event == "consent":
            core.db.execute("UPDATE workspaces SET consent=NULL WHERE id=?", (wid,))
            return popup(payload)
        return popup(payload, citations=["invented"])

    model(monkeypatch, c, generate=generate)
    service = MeetingService(core, c.app.state.answer)
    body = MeetingInput.model_validate(request())
    analysis = Extraction.model_validate(extraction())
    prepared = service.retrieve_classified(wid, body, analysis)
    result = service.generate_classified(wid, body, analysis, prepared)
    assert result["status"] == "unavailable" and result["evidence"] == [] and result["popup"] is None


def test_retrieval_of_classified_topic_without_evidence_still_finishes(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c)
    analysis = Extraction.model_validate(
        extraction(query="unrelated-random-zzzzzz", intent="context", claim="")
    )
    result = MeetingService(core, c.app.state.answer).retrieve_classified(
        wid, MeetingInput.model_validate(request("새로운 주제를 이야기해야겠어요.")), analysis
    )
    assert result["status"] == "insufficient_evidence" and not calls


def test_classifier_timeout_is_retryable_error_not_low_importance(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)

    def timeout(_):
        raise TimeoutError()

    fake_classifier(monkeypatch, c, callback=timeout)
    with pytest.raises(TimeoutError):
        run_classifier(c, core, wid)


def test_generation_budget_expiry_does_not_return_prepared_evidence(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c)
    service = MeetingService(core, c.app.state.answer)
    body = MeetingInput.model_validate(request())
    analysis = Extraction.model_validate(extraction())
    prepared = service.retrieve_classified(wid, body, analysis)
    result = service.generate_classified(wid, body, analysis, prepared, timeout_seconds=0)
    assert result["status"] == "unavailable" and result["reason"] == "MEETING_TIMEOUT"
    assert result["evidence"] == [] and not calls


def test_generation_receives_whole_long_context_including_its_negation(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c)
    service = MeetingService(core, c.app.state.answer)
    context = "이전 회의 설명 " * 300 + "운영서버와 개발서버는 같은 환경이 아니에요."
    body = MeetingInput.model_validate(request(context=[{"text": context}]))
    analysis = Extraction.model_validate(extraction())
    prepared = service.retrieve_classified(wid, body, analysis)
    result = service.generate_classified(wid, body, analysis, prepared)
    assert result["status"] == "popup" and len(calls) == 1
    assert calls[0][1]["context"][0]["text"] == context


def test_generation_reports_input_limit_instead_of_truncating_large_context(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c)
    service = MeetingService(core, c.app.state.answer)
    body = MeetingInput.model_validate(request(context=[{"text": "가" * 10000}] * 3))
    analysis = Extraction.model_validate(extraction())
    prepared = service.retrieve_classified(wid, body, analysis)
    result = service.generate_classified(wid, body, analysis, prepared)
    assert result["status"] == "unavailable" and result["reason"] == "LLM_INPUT_LIMIT"
    assert result["evidence"] == [] and not calls
    assert all(len(item.text) == 10000 for item in body.context)
