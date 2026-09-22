"""Synthetic meeting pipeline tests: no microphone, external provider, or real company data."""

import json
from types import SimpleNamespace

import pytest
from test_llm_management import save
from test_rag import create, index

from meetingbot_rag.meeting import Extraction, PopupOutput, validate_popup

CLAIM = "운영서버 로그 기록이 45일 동안 서버에 남아요."
POLICY = "운영서버 로그 기록의 보관 기간은 90일입니다. 개발서버 로그 기록은 30일 동안 보관합니다."


def request(text=CLAIM, **updates):
    return {
        "session_id": "session-1",
        "utterance": {
            "utterance_id": "utterance-1",
            "revision": 1,
            "text": text,
            "status": "stable",
            "speaker_id": "speaker-1",
            "start_ms": 0,
            "end_ms": 2500,
        },
        "context": [{"text": "서버 운영 정책을 검토합니다.", "speaker_id": "speaker-2"}],
        **updates,
    }


def extraction(**updates):
    return {
        "relevant": True,
        "keywords": ["로그", "보관 기간"],
        "query": "운영서버 로그 보관 기간",
        "intent": "fact_check",
        "claim": CLAIM,
        **updates,
    }


def popup(payload, **updates):
    evidence = payload["evidence"][0]
    return {
        "status": "popup",
        "assessment": "contradicted",
        "scope_match": True,
        "kind": "warning",
        "title": "로그 보관 기간 정정",
        "message": "운영서버 로그는 90일, 개발서버 로그는 30일 보관합니다.",
        "confidence": 0.94,
        "citations": [evidence["evidence_id"]],
        "support_quotes": [{"evidence_id": evidence["evidence_id"], "quote": POLICY}],
        **updates,
    }


def ready(client, approve=True):
    c, root, _ = client
    c.app.state.access.owner("session-1", "superadmin")
    (root / "policy.md").write_text("# 로그 보관 정책\n\n" + POLICY)
    wid = create(c, "")
    revision = index(c, wid)["revision_id"]
    if approve:
        settings = save(c, enabled=True, api_key="synthetic-key", default_model="synthetic-model")
        result = c.patch(
            f"/api/rag/workspaces/{wid}",
            json={
                "external_llm_approved": True,
                "provider_id": settings["provider_id"],
            },
        )
        assert result.status_code == 200
    return wid, revision


def model(monkeypatch, c, extract=None, generate=None):
    calls, configs = [], []

    class FakeLLM:
        def invoke(self, messages):
            payload = json.loads(messages[1][1])
            calls.append((messages[0][1], payload))
            fn = (generate or popup) if "evidence" in payload else (extract or (lambda _: extraction()))
            value = fn(payload)
            return SimpleNamespace(content=value if isinstance(value, str) else json.dumps(value))

    def create_model(config):
        configs.append(config)
        return FakeLLM()

    monkeypatch.setattr(c.app.state.answer.factory, "create", create_model)
    return calls, configs


def analyze(c, wid, body=None):
    response = c.post(f"/api/rag/workspaces/{wid}/meeting/analyze", json=body or request())
    assert response.status_code == 200, response.text
    return response.json()


def test_two_stages_grounded_popup_and_revision(client, monkeypatch):
    c, _, _ = client
    wid, revision = ready(client)
    calls, configs = model(monkeypatch, c)
    result = analyze(c, wid)
    assert result["status"] == "popup", result
    assert result["revision_id"] == revision
    assert result["session_id"] == "session-1" and result["utterance_revision"] == 1
    assert result["analysis"]["claim"] == CLAIM
    assert result["popup"]["kind"] == "warning" and result["popup"]["color"] == "red"
    assert len(calls) == 2 and "evidence" not in calls[0][1] and calls[1][1]["evidence"]
    assert calls[0][1]["context"][0]["text"] == "서버 운영 정책을 검토합니다."
    assert "신뢰할 수 없는" in calls[0][0] and "신뢰할 수 없는" in calls[1][0]
    assert configs[0].timeout_seconds <= 12 and configs[1].timeout_seconds <= 20
    assert configs[0].max_output_tokens <= 800 and configs[1].max_output_tokens <= 1800
    assert result["timings_ms"]["total"] >= 0
    evidence = result["evidence"][0]
    assert result["popup"]["citations"] == [evidence["evidence_id"]]
    assert (
        c.get(
            f"/api/rag/workspaces/{wid}/evidence/{evidence['evidence_id']}", params={"revision_id": revision}
        ).status_code
        == 200
    )
    # Speaker/finality revision updates replace the same utterance's popup.
    body = request()
    body["utterance"].update(revision=2, status="final", speaker_id="speaker-3")
    second = analyze(c, wid, body)
    assert second["popup"]["id"] == result["popup"]["id"] and second["utterance_revision"] == 2


@pytest.mark.parametrize("enabled,consent", [(False, False), (True, False), (False, True)])
def test_no_transcript_transmission_without_global_and_workspace_approval(
    client, monkeypatch, enabled, consent
):
    c, _, core = client
    wid, _ = ready(client, approve=consent)
    if not consent:
        save(c, enabled=enabled, api_key="synthetic-key", default_model="synthetic-model")
    elif not enabled:
        save(c, enabled=False)
    calls, _ = model(monkeypatch, c)
    result = analyze(c, wid)
    assert result["status"] == "unavailable" and result["reason"] == "EXTERNAL_LLM_NOT_APPROVED"
    assert result["popup"] is None and result["evidence"] == [] and calls == []
    assert core.db.one("SELECT COUNT(*) n FROM query_runs")["n"] == 0


def test_irrelevant_speech_skips_retrieval_and_second_llm(client, monkeypatch):
    c, _, core = client
    wid, _ = ready(client)
    calls, _ = model(
        monkeypatch,
        c,
        extract=lambda _: extraction(
            relevant=False,
            keywords=[],
            query="",
            intent="none",
            claim="",
        ),
    )
    monkeypatch.setattr(core.retrieval, "search", lambda *_a, **_k: pytest.fail("No search for small talk"))
    result = analyze(c, wid, request("안녕하세요."))
    assert result["status"] == "suppressed" and result["popup"] is None and len(calls) == 1


def test_no_evidence_skips_generation(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)
    calls, _ = model(
        monkeypatch,
        c,
        extract=lambda _: extraction(
            query="unrelated-random-zzzzzz",
            intent="context",
            claim="",
        ),
    )
    result = analyze(c, wid, request("내년 달 기지에 배치할 양자 로봇 수는 몇 대인가요?"))
    assert result["status"] == "insufficient_evidence" and result["reason"] == "NO_EVIDENCE"
    assert len(calls) == 1 and result["popup"] is None


@pytest.mark.parametrize("stage", ["extraction", "retrieval", "generation"])
def test_revocation_stops_next_transmission_and_late_popup(client, monkeypatch, stage):
    c, _, core = client
    wid, _ = ready(client)

    def revoke():
        core.db.execute("UPDATE workspaces SET consent=NULL WHERE id=?", (wid,))

    def extract(_):
        if stage == "extraction":
            revoke()
        return extraction()

    def generate(payload):
        if stage == "generation":
            revoke()
        return popup(payload)

    search = core.retrieval.search

    def retrieve(*args, **kwargs):
        result = search(*args, **kwargs)
        if stage == "retrieval":
            revoke()
        return result

    monkeypatch.setattr(core.retrieval, "search", retrieve)
    calls, _ = model(monkeypatch, c, extract, generate)
    result = analyze(c, wid)
    assert result["status"] == "unavailable" and result["reason"] == "EXTERNAL_LLM_NOT_APPROVED"
    assert result["popup"] is None and result["evidence"] == []
    assert len(calls) == (2 if stage == "generation" else 1)


def test_settings_change_between_stages_stops_send(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)

    def extract(_):
        save(c, temperature=0.2)
        return extraction()

    calls, _ = model(monkeypatch, c, extract)
    result = analyze(c, wid)
    assert result["reason"] == "SETTINGS_CHANGED" and len(calls) == 1


@pytest.mark.parametrize("stage", ["retrieval", "generation"])
def test_source_revocation_removes_previously_retrieved_evidence(client, monkeypatch, stage):
    c, _, core = client
    wid, _ = ready(client)

    def revoke():
        core.s.source_roots_file.write_text("roots: []")

    search = core.retrieval.search

    def retrieve(*args, **kwargs):
        result = search(*args, **kwargs)
        if stage == "retrieval":
            revoke()
        return result

    def generate(payload):
        revoke()
        return popup(payload)

    monkeypatch.setattr(core.retrieval, "search", retrieve)
    calls, _ = model(monkeypatch, c, generate=generate)
    result = analyze(c, wid)
    assert result["status"] == "unavailable" and result["popup"] is None and result["evidence"] == []
    assert len(calls) == (1 if stage == "retrieval" else 2)


def test_input_budget_prevents_first_transmission(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)
    save(c, input_chars=4000)
    calls, _ = model(monkeypatch, c)
    result = analyze(c, wid, request(text="가" * 4000))
    assert result["reason"] == "LLM_INPUT_LIMIT" and not calls


@pytest.mark.parametrize("bad", ["not json", '{"relevant":true}', {**extraction(), "keywords": ["x" * 61]}])
def test_malformed_extraction_is_fail_safe(client, monkeypatch, bad):
    c, _, _ = client
    wid, _ = ready(client)
    calls, _ = model(monkeypatch, c, extract=lambda _: bad)
    result = analyze(c, wid)
    assert result["status"] == "unavailable" and result["reason"] == "INVALID_MEETING_LLM_OUTPUT"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"citations": ["made-up"]}, "INVALID_LLM_CITATIONS"),
        ({"citations": []}, "INVALID_LLM_CITATIONS"),
        ({"support_quotes": []}, "INVALID_LLM_CITATIONS"),
        (
            {"support_quotes": [{"evidence_id": "made-up", "quote": "자료에 없는 인용문입니다."}]},
            "INVALID_LLM_CITATIONS",
        ),
        ({"kind": "custom-red"}, "INVALID_MEETING_LLM_OUTPUT"),
        ({"color": "purple"}, "INVALID_MEETING_LLM_OUTPUT"),
        ({"message": "x" * 801}, "INVALID_MEETING_LLM_OUTPUT"),
        ({"confidence": float("nan")}, "INVALID_MEETING_LLM_OUTPUT"),
    ],
)
def test_untrusted_popup_cannot_forge_citations_or_presentation(client, monkeypatch, updates, reason):
    c, _, _ = client
    wid, _ = ready(client)
    model(monkeypatch, c, generate=lambda p: popup(p, **updates))
    result = analyze(c, wid)
    assert result["status"] == "unavailable" and result["reason"] == reason
    assert result["popup"] is None


@pytest.mark.parametrize(
    "kind,assessment,scope,confidence,expected",
    [
        ("warning", "contradicted", True, 0.95, "red"),
        ("success", "supported", True, 0.95, "green"),
        ("caution", "supplemental", False, 0.9, "orange"),
        ("info", "supplemental", False, 0.9, "blue"),
        ("warning", "contradicted", False, 0.95, "orange"),
        ("success", "supported", False, 0.95, "orange"),
        ("warning", "uncertain", True, 0.95, "orange"),
        ("success", "contradicted", True, 0.95, "orange"),
        ("warning", "contradicted", True, 0.75, "orange"),
    ],
)
def test_severity_scope_and_grounding_rules(kind, assessment, scope, confidence, expected):
    evidence = [{"evidence_id": "e1", "text": POLICY}]
    generated = PopupOutput.model_validate(
        popup(
            {"evidence": evidence}, kind=kind, assessment=assessment, scope_match=scope, confidence=confidence
        )
    )
    status, result, _ = validate_popup(generated, evidence, Extraction.model_validate(extraction()))
    assert status == "popup" and result["color"] == expected
    if kind in {"warning", "success"} and expected == "orange":
        assert result["message"] != generated.message and "확인" in result["message"]


def test_conflicts_need_both_sources_and_low_confidence_abstains():
    evidence = [{"evidence_id": "e1", "text": POLICY}]
    claim = Extraction.model_validate(extraction())
    generated = PopupOutput.model_validate(
        popup({"evidence": evidence}, assessment="conflicting", kind="caution")
    )
    assert validate_popup(generated, evidence, claim) == (
        "insufficient_evidence",
        None,
        "CONFLICT_NEEDS_BOTH_SOURCES",
    )
    evidence.append({"evidence_id": "e2", "text": "운영서버 로그 기록의 보관 기간은 30일입니다."})
    generated.citations.append("e2")
    generated.support_quotes.append(
        type(generated.support_quotes[0])(evidence_id="e2", quote=evidence[1]["text"])
    )
    assert validate_popup(generated, evidence, claim)[1]["color"] == "orange"
    generated.confidence = 0.4
    assert validate_popup(generated, evidence, claim) == ("insufficient_evidence", None, "LOW_CONFIDENCE")


@pytest.mark.parametrize("intent,expected", [("practical_guidance", "orange"), ("context", "blue")])
def test_green_is_reserved_for_fact_checks_preserving_supported_guidance(intent, expected):
    text = "운영서버 접속에는 개인키가 필요합니다. 발급 안내는 보안 포털에 있으며 담당자는 김보안입니다."
    evidence = [{"evidence_id": "e1", "text": text}]
    message = "개인키 발급 안내는 보안 포털에서 확인하세요. 김보안 담당자에게 발급을 신청할 수 있습니다."
    generated = PopupOutput.model_validate(
        popup(
            {"evidence": evidence},
            assessment="supported",
            scope_match=True,
            kind="success",
            title="개인키 발급 안내",
            message=message,
            support_quotes=[{"evidence_id": "e1", "quote": text}],
        )
    )
    claim = Extraction.model_validate(extraction(intent=intent, claim="운영서버 접속에는 개인키가 필요해요."))
    status, result, reason = validate_popup(generated, evidence, claim)
    assert status == "popup" and reason is None and result["color"] == expected
    assert result["message"] == message and result["citations"] == ["e1"]


def test_busy_and_provider_timeout_release_shared_gate(client, monkeypatch):
    c, _, _ = client
    wid, _ = ready(client)
    gate = c.app.state.answer.factory.gate
    calls, _ = model(monkeypatch, c)
    for _ in range(3):
        gate.acquire()
    try:
        assert analyze(c, wid)["reason"] == "LLM_BUSY" and not calls
    finally:
        for _ in range(3):
            gate.release()

    def timeout(_):
        raise TimeoutError()

    model(monkeypatch, c, extract=timeout)
    assert analyze(c, wid)["reason"] == "PROXY_TIMEOUT"
    assert gate.acquire(blocking=False)
    gate.release()


def test_request_validation_and_auth(client):
    c, _, _ = client
    wid, _ = ready(client, approve=False)
    url = f"/api/rag/workspaces/{wid}/meeting/analyze"
    assert c.post(url, json=request(), headers={"Authorization": ""}).status_code == 401
    for changes in (
        {"status": "draft"},
        {"text": " "},
        {"text": "x" * 10001},
        {"revision": -1},
        {"end_ms": -1},
        {"start_ms": 3000},
        {"revision": True},
    ):
        body = request()
        body["utterance"].update(changes)
        assert c.post(url, json=body).status_code == 422
    assert c.post(url, json=request(context=[{"text": "x"}] * 4)).status_code == 422
    assert c.post(url, json=request(context=[{"text": "x" * 10001}])).status_code == 422


@pytest.mark.parametrize("role", ["visitor", "admin", "superadmin", "installation"])
def test_direct_meeting_analysis_requires_the_recording_owner(client, monkeypatch, role):
    c, _, _ = client
    wid, _ = ready(client, approve=False)
    access = c.app.state.access
    owner = access.issue_key("recording owner", "visitor")
    access.owner("private-session", owner["id"])
    caller = (
        c.headers["Authorization"]
        if role == "installation"
        else "Bearer " + access.issue_key("different account", role)["key"]
    )
    calls = []

    def analyze_owned(workspace_id, body):
        calls.append((workspace_id, body.session_id))
        return {"status": "suppressed", "session_id": body.session_id}

    monkeypatch.setattr(c.app.state.meeting, "analyze", analyze_owned)
    url = f"/api/rag/workspaces/{wid}/meeting/analyze"
    for sid in ("private-session", "ownerless-session"):
        denied = c.post(url, json=request(session_id=sid), headers={"Authorization": caller})
        assert denied.status_code == 404
        assert denied.json()["error_code"] == "SESSION_NOT_FOUND"
    assert calls == []
    allowed = c.post(
        url,
        json=request(session_id="private-session"),
        headers={"Authorization": "Bearer " + owner["key"]},
    )
    assert allowed.status_code == 200
    assert calls == [(wid, "private-session")]


def test_revision_must_belong_to_workspace_before_transmission(client, monkeypatch):
    c, _, _ = client
    wid, revision = ready(client)
    other = create(c, "", "다른 자료")
    policy = c.app.state.answer.policy()
    c.patch(
        f"/api/rag/workspaces/{other}",
        json={"external_llm_approved": True, "provider_id": policy["provider_id"]},
    )
    calls, _ = model(monkeypatch, c)
    result = analyze(c, other, request(revision_id=revision))
    assert result["reason"] == "REVISION_NOT_READY" and not calls
    assert result["evidence"] == [] and result["popup"] is None
