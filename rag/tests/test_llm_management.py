import json
import sqlite3
from types import SimpleNamespace

import pytest
from conftest import ask
from test_rag import create, index

from meetingbot_rag.db import SCHEMA, Database
from meetingbot_rag.llm_settings import PromptInput, PromptService
from meetingbot_rag.sources import RagError


def save(c, **data):
    version = c.get("/api/rag/llm/settings").json()["version"]
    response = c.patch("/api/rag/llm/settings", json={"expected_version": version, **data})
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    "route", ["/llm/settings", "/llm/models", "/llm/codex/status", "/prompts", "/prompts/active"]
)
def test_admin_auth(client, route):
    c, _, _ = client
    assert c.get("/api/rag" + route, headers={"Authorization": ""}).status_code == 401


def test_settings_secret_scope_conflict_and_consent(client):
    c, root, core = client
    wid = create(c, "")
    current = save(c, api_key="test-private-key", default_model="test-model", enabled=True)
    assert (
        current["api_key_present"]
        and "test-private-key" not in json.dumps(current)
        and "api_key" not in current
    )
    assert (
        c.patch(
            f"/api/rag/workspaces/{wid}",
            json={"external_llm_approved": True, "provider_id": current["provider_id"]},
        ).status_code
        == 200
    )
    save(c, api_key="")
    assert c.app.state.answer.settings.snapshot()[0].api_key == "test-private-key"
    assert c.get(f"/api/rag/workspaces/{wid}").json()["consent"] == current["provider_id"]
    assert (
        c.patch(
            "/api/rag/llm/settings", json={"expected_version": current["version"], "enabled": False}
        ).status_code
        == 409
    )
    save(c, default_model="another-model")
    assert c.get(f"/api/rag/workspaces/{wid}").json()["consent"] is None
    next = save(c, base_url="http://127.0.0.1:9999")
    assert not next["api_key_present"] and next["default_model"] == ""
    save(c, api_key="replacement", temperature=0.3, reasoning_effort="low")
    next = save(c, temperature=None, reasoning_effort=None, clear_api_key=True)
    assert next["temperature"] is None and next["reasoning_effort"] is None and not next["api_key_present"]


@pytest.mark.parametrize(
    "changes",
    [
        {"base_url": "file:///etc/passwd"},
        {"base_url": "https://key:secret@example.test/v1"},
        {"base_url": "http://localhost:8317/v1?key=private"},
        {"base_url": "http://localhost:8317/anything"},
        {"reasoning_effort": "invalid"},
        {"max_output_tokens": 0},
        {"enabled": None},
        {"temperature": 9},
        {"default_model": "bad\nmodel"},
        {"api_key": "private\nsecret"},
    ],
)
def test_invalid_settings_are_sanitized(client, changes):
    c, _, _ = client
    r = c.patch("/api/rag/llm/settings", json={"expected_version": 0, **changes})
    assert r.status_code == 422
    assert "private" not in r.text and "secret" not in r.text
    assert c.get("/api/rag/llm/settings").json()["version"] == 0


def test_catalog_checks_use_real_completion_and_options(client, monkeypatch):
    c, _, core = client
    save(c, api_key="test-key", default_model="listed-but-offline")
    factory = c.app.state.answer.factory
    monkeypatch.setattr(factory, "models", lambda: {"models": ["listed-but-offline"]})

    class Broken:
        def invoke(self, *_):
            raise TimeoutError()

    monkeypatch.setattr(factory, "create", lambda *_: Broken())
    check = c.post("/api/rag/llm/check", json={}).json()
    assert check["models_ok"] and not check["completion_ok"] and check["error_code"] == "PROXY_TIMEOUT"
    assert c.get("/api/rag/llm/settings").json()["last_check"]["error_code"] == "PROXY_TIMEOUT"
    save(c, reasoning_effort="high")
    assert c.get("/api/rag/llm/settings").json()["last_check"] is None

    class Good:
        def invoke(self, *_):
            return SimpleNamespace(content='{"ok":true}')

    monkeypatch.setattr(factory, "create", lambda *_: Good())
    check = c.post("/api/rag/llm/check", json={}).json()
    assert check["completion_ok"] and check["json_ok"]
    for _ in range(3):
        factory.gate.acquire()
    try:
        assert c.post("/api/rag/llm/check", json={}).status_code == 429
    finally:
        for _ in range(3):
            factory.gate.release()


def test_catalog_rejects_response_for_old_connection(client):
    c, _, _ = client
    service = c.app.state.answer.settings
    save(c, api_key="key1")
    config, _ = service.snapshot()
    service.cache_catalog(config, ["model1"])
    save(c, api_key="key2")
    assert service.catalog()["models"] == []
    with pytest.raises(RagError, match="SETTINGS_CHANGED"):
        service.cache_catalog(config, ["late-model"])


def test_prompts_immutable_restore_optimistic_and_preview(client):
    c, _, _ = client
    original = c.get("/api/rag/prompts/active").json()
    r = c.post(
        "/api/rag/prompts",
        json={
            "name": "시험 프롬프트",
            "content": "질문에 정확한 한국어로 답변하고 반드시 제공된 근거를 인용하세요.",
            "note": "테스트",
            "expected_active_id": original["id"],
        },
    )
    assert r.status_code == 201
    new = r.json()["prompt"]
    assert c.get("/api/rag/prompts/active").json() == original
    assert (
        c.post(
            f"/api/rag/prompts/{new['id']}/activate", json={"expected_active_id": original["id"]}
        ).status_code
        == 200
    )
    assert (
        c.post(
            f"/api/rag/prompts/{original['id']}/activate", json={"expected_active_id": original["id"]}
        ).status_code
        == 409
    )
    r = c.post(f"/api/rag/prompts/{original['id']}/restore", json={"expected_active_id": new["id"]})
    restored = r.json()["prompt"]
    assert restored["id"] != original["id"] and restored["content"] == original["content"]
    assert restored["sequence"] == 3 and restored["restored_from_id"] == original["id"]
    assert c.get(f"/api/rag/prompts/{original['id']}").json() == original
    for case in ["supported", "missing", "conflict", "injection"]:
        r = c.post("/api/rag/prompts/preview", json={"case": case}).json()
        assert r["synthetic"] and "고정 출력 계약" in r["messages"][0]["content"]
        assert "sample-1" in r["messages"][1]["content"]
    # Maximum Korean prompt is accepted without leaking request bodies in errors.
    assert c.post("/api/rag/prompts/preview", json={"content": "한" * 12000}).status_code == 200


def test_live_preview_and_rag_use_saved_prompt_with_provenance(client, monkeypatch):
    c, root, _ = client
    (root / "policy.md").write_text("운영 로그 보관 기간은 90일입니다.")
    wid = create(c, "")
    assert index(c, wid)["state"] == "READY"
    cfg = save(c, api_key="test-key", default_model="test-model", enabled=True)
    c.patch(
        f"/api/rag/workspaces/{wid}", json={"external_llm_approved": True, "provider_id": cfg["provider_id"]}
    )
    active = c.get("/api/rag/prompts/active").json()
    calls = []

    class Good:
        def invoke(self, messages):
            calls.append(messages)
            payload = json.loads(messages[1][1])
            eid = payload["evidence"][0]["evidence_id"]
            return SimpleNamespace(
                content=json.dumps({"status": "answered", "answer": "90일입니다.", "citations": [eid]})
            )

    monkeypatch.setattr(c.app.state.answer.factory, "create", lambda *_: Good())
    r = c.post("/api/rag/prompts/test", json={"case": "injection"}).json()
    assert r["result"]["citations"] == ["sample-1"]
    r = ask(c, f"/api/rag/workspaces/{wid}/questions", json={"query": "로그 보관 기간"})
    assert (
        r["status"] == "answered"
        and r["llm"]["prompt_id"] == active["id"]
        and r["llm"]["model"] == "test-model"
    )
    assert active["content"] in calls[-1][0][1]
    assert c.get(f"/api/rag/workspaces/{wid}/questions").json()[0]["llm"] == r["llm"]
    save(c, enabled=False)
    r = ask(c, f"/api/rag/workspaces/{wid}/questions", json={"query": "로그 보관 기간"})
    assert r["reason"] == "EXTERNAL_LLM_NOT_APPROVED" and len(calls) == 2


def test_schema_one_migration_and_saved_state_survives_reopen(env, tmp_path):
    path = tmp_path / "legacy.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        db.execute("INSERT INTO workspaces VALUES('keep','자료','설명',1,NULL,0)")
    core = SimpleNamespace(db=Database(path), s=env[0])
    assert core.db.one("SELECT version FROM schema_version")["version"] == 9
    assert core.db.one("SELECT name FROM workspaces WHERE id='keep'")["name"] == "자료"
    prompts = PromptService(core)
    original = prompts.active()
    revision = prompts.save(
        PromptInput(
            name="재시작",
            content="서버 재시작 뒤에도 이 프롬프트가 그대로 유지되어야 합니다.",
            expected_active_id=original["id"],
            activate=True,
        )
    )["prompt"]
    core.db.close()
    core.db = Database(path)
    assert PromptService(core).active() == revision
    assert core.db.one("SELECT COUNT(*) n FROM prompt_versions")["n"] == 2
    core.db.close()


def test_managed_proxy_account_display_does_not_expose_credentials(client, tmp_path, monkeypatch):
    c, _, _ = client
    bridge = c.app.state.proxy
    bridge.path = tmp_path
    monkeypatch.setattr(bridge, "credentials", lambda: {"management_key": "private"})
    files = [
        {"type": "codex", "email": "first@example.test", "status": "active"},
        {"type": "codex", "email": "second@example.test", "status": "active"},
        {"type": "codex", "email": "off@example.test", "status": "active", "disabled": True},
        {"type": "codex", "email": "error@example.test", "status": "error"},
        {"type": "codex", "email": "busy@example.test", "status": "active", "unavailable": True},
        {"type": "codex", "email": "", "status": "new-upstream-status"},
        {"type": "claude", "email": "excluded@example.test", "status": "active"},
    ]
    for account_index, item in enumerate(files):
        item.update(access_token="private", refresh_token="private", id_token="private",
                    path="/private/auth.json", status_message="private",
                    name=f"account-{account_index}.json", source="file")
    monkeypatch.setattr(bridge, "request", lambda *args, **kwargs: {"files": files})
    response = c.get("/api/rag/llm/codex/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] and data["account_count"] == 2
    assert [{k: item[k] for k in ("email", "status")} for item in data["accounts"]] == [
        {"email": "firs***@ex***st", "status": "active"},
        {"email": "seco***@ex***st", "status": "active"},
        {"email": "off***@ex***st", "status": "disabled"},
        {"email": "erro***@ex***st", "status": "error"},
        {"email": "busy***@ex***st", "status": "unavailable"},
        {"email": None, "status": "unknown"},
    ]
    assert all(len(item["id"]) == 64 and item["manageable"] for item in data["accounts"])
    assert data["selected_account_id"] is None and data["enabled_count"] == 5
    assert "private" not in response.text and "@example.test" not in response.text
    assert "account-0.json" not in response.text
    files.clear()
    data = c.get("/api/rag/llm/codex/status").json()
    assert data["accounts"] == [] and not data["connected"] and data["account_count"] == 0


@pytest.mark.parametrize("email, expected", [
    ("abcdef@gmail.com", "abcd***@gm***om"),
    ("a@b.co", "a***@b.***co"),
    ("a@b.c", "a***@b.***c"),
    ("a@b", "a***@b***"),
    (None, None), ("broken", None), ("@gmail.com", None), ("a@", None),
])
def test_proxy_email_mask(email, expected):
    from meetingbot_rag.managed_proxy import masked_email
    assert masked_email(email) == expected


@pytest.fixture
def proxy_accounts(client, tmp_path, monkeypatch):
    import copy
    c, _, _ = client
    bridge = c.app.state.proxy
    bridge.path = tmp_path
    monkeypatch.setattr(bridge, "credentials", lambda: {"management_key": "private"})
    files = [
        {"type": "codex", "name": "first.json", "email": "first@example.test",
         "status": "active", "disabled": False, "source": "file"},
        {"type": "codex", "name": "second.json", "email": "second@example.test",
         "status": "disabled", "disabled": True, "source": "file"},
        {"type": "claude", "name": "other.json", "status": "active", "disabled": False},
    ]
    calls = []

    def request(method, path, **kwargs):
        if method == "GET" and path == "auth-files":
            return {"files": copy.deepcopy(files)}
        calls.append((method, path, kwargs))
        if method == "PATCH":
            item = next(item for item in files if item["name"] == kwargs["json"]["name"])
            item["disabled"] = kwargs["json"]["disabled"]
            item["status"] = "disabled" if item["disabled"] else "active"
        elif method == "DELETE":
            files[:] = [item for item in files if item["name"] != kwargs["params"]["name"]]
        else:
            raise AssertionError("Unexpected management operation")
        return {"status": "ok"}

    monkeypatch.setattr(bridge, "request", request)
    return c, bridge, files, calls, request


def test_proxy_select_switch_delete_and_stale_actions(proxy_accounts):
    c, bridge, files, calls, _ = proxy_accounts
    before = bridge.status()
    first, second = before["accounts"]
    assert before["selected_account_id"] == first["id"]
    body = {"account_id": second["id"], "expected_revision": before["revision"]}
    selected = c.post("/api/rag/llm/codex/accounts/select", json=body)
    assert selected.status_code == 200
    selected = selected.json()
    assert selected["selected_account_id"] == second["id"] and selected["enabled_count"] == 1
    assert files[0]["disabled"] and not files[1]["disabled"] and not files[2]["disabled"]
    assert [call[2]["json"] for call in calls] == [
        {"name": "first.json", "disabled": True}, {"name": "second.json", "disabled": False}]
    assert c.post("/api/rag/llm/codex/accounts/delete", json=body).status_code == 409
    assert len(calls) == 2
    switched = c.post("/api/rag/llm/codex/accounts/select", json={
        "account_id": first["id"], "expected_revision": selected["revision"]}).json()
    assert switched["selected_account_id"] == first["id"]
    deleted = c.post("/api/rag/llm/codex/accounts/delete", json={
        "account_id": second["id"], "expected_revision": switched["revision"]})
    assert deleted.status_code == 200 and len(deleted.json()["accounts"]) == 1
    assert calls[-1] == ("DELETE", "auth-files", {"params": {"name": "second.json"}})
    last = deleted.json()
    deleted = c.post("/api/rag/llm/codex/accounts/delete", json={
        "account_id": first["id"], "expected_revision": last["revision"]})
    assert deleted.status_code == 200 and deleted.json()["accounts"] == []
    assert not deleted.json()["connected"] and deleted.json()["selected_account_id"] is None
    assert files[0]["type"] == "claude"


def test_proxy_switch_rolls_back_lost_response(proxy_accounts, monkeypatch):
    c, bridge, files, calls, request = proxy_accounts
    before = bridge.status()
    failed = False

    def flaky(method, path, **kwargs):
        nonlocal failed
        result = request(method, path, **kwargs)
        if method == "PATCH" and kwargs["json"]["name"] == "second.json" and not failed:
            failed = True
            raise RagError("CODEX_CONNECTION_FAILED", "private", 502)
        return result

    monkeypatch.setattr(bridge, "request", flaky)
    response = c.post("/api/rag/llm/codex/accounts/select", json={
        "account_id": before["accounts"][1]["id"], "expected_revision": before["revision"]})
    assert response.status_code == 502 and "private" not in response.text
    assert not files[0]["disabled"] and files[1]["disabled"]
    assert bridge.status()["revision"] == before["revision"]


@pytest.mark.parametrize("action", ["select", "delete"])
def test_proxy_account_actions_reject_unauthorized_and_invalid_targets(proxy_accounts, action):
    c, bridge, files, calls, _ = proxy_accounts
    before = bridge.status()
    body = {"account_id": before["accounts"][0]["id"], "expected_revision": before["revision"]}
    url = "/api/rag/llm/codex/accounts/" + action
    assert c.post(url, json=body, headers={"Authorization": ""}).status_code == 401
    assert c.post(url, json={**body, "account_id": "../private.json"}).status_code == 422
    assert c.post(url, json={**body, "account_id": "0" * 64}).status_code == 404
    files[0]["runtime_only"] = True
    assert c.post(url, json=body).status_code == 409
    assert calls == []


def test_managed_proxy_rejects_unmatched_callback(client, tmp_path, monkeypatch):
    c, _, _ = client
    bridge = c.app.state.proxy
    bridge.path = tmp_path
    (tmp_path / "pending-login.json").write_text(
        json.dumps({"state": "pending", "url": "https://auth.openai.com/oauth/authorize"})
    )
    calls = []
    monkeypatch.setattr(bridge, "request", lambda *args, **kwargs: calls.append((args, kwargs)))
    for url in [
        "http://localhost:1455/auth/callback?state=wrong&code=private",
        "https://evil.test/auth/callback?state=pending&code=private",
        "http://localhost:1455/auth/callback?state=pending",
    ]:
        response = c.post("/api/rag/llm/codex/callback", json={"redirect_url": url})
        assert response.status_code == 400 and "private" not in response.text
    assert calls == []
    assert (
        c.post(
            "/api/rag/llm/codex/callback",
            json={"redirect_url": "http://localhost:1455/auth/callback?state=pending&code=private"},
        ).status_code
        == 200
    )
    assert calls[0][1]["json"] == {"provider": "codex", "state": "pending", "code": "private"}


def test_langchain_openai_http_roundtrip(client):
    """Exercise the real SDK wire format, auth and parser without using an account."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    c, _, _ = client
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            assert self.path == "/v1/models"
            self.send({"data": [{"id": "synthetic-codex"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, self.headers.get("Authorization"), body))
            if len(body["messages"]) == 1:
                content = '{"ok":true}'
            else:
                content = json.dumps(
                    {"status": "answered", "answer": "90일입니다.", "citations": ["sample-1"]}
                )
            self.send(
                {
                    "id": "test-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                }
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        save(
            c,
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="synthetic-key",
            default_model="synthetic-codex",
            reasoning_effort="low",
        )
        check = c.post("/api/rag/llm/check", json={}).json()
        assert check["completion_ok"] and check["json_ok"] and check["models_ok"]
        preview = c.post("/api/rag/prompts/test", json={"case": "supported"})
        assert preview.status_code == 200, preview.text
        assert preview.json()["result"]["answer"] == "90일입니다."
        assert len(seen) == 2
        for path, auth, body in seen:
            assert path == "/v1/chat/completions" and auth == "Bearer synthetic-key"
            assert body["reasoning_effort"] == "low" and "temperature" not in body
            assert not body.get("tools") and not body["stream"]
        assert "고정 출력 계약" in seen[-1][2]["messages"][0]["content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_empty_catalog_requires_account_login(client, monkeypatch):
    c, _, _ = client
    save(c, api_key="test-key", default_model="gpt-5.6-terra")
    factory = c.app.state.answer.factory
    monkeypatch.setattr(factory, "models", lambda: {"models": []})
    calls = []
    monkeypatch.setattr(factory, "create", lambda *_: calls.append(1))
    result = c.post("/api/rag/llm/check", json={}).json()
    assert result["error_code"] == "PROXY_NO_MODELS" and not result["completion_ok"]
    assert calls == []


def test_related_answer_requires_real_citations_and_preview_uses_policy(client, monkeypatch):
    from meetingbot_rag.answers import parse_answer

    c, _, _ = client
    sources = [{"evidence_id": "sample-1", "text": "김치볶음밥 조리법"}]
    output = {
        "status": "related_evidence",
        "answer": "마늘볶음밥의 직접 자료는 없지만 김치볶음밥의 조리법을 안내합니다.",
        "citations": ["sample-1"],
    }
    assert parse_answer(json.dumps(output), sources)["status"] == "related_evidence"
    for citations in ([], ["invented"]):
        with pytest.raises(RagError):
            parse_answer(json.dumps({**output, "citations": citations}), sources)
    save(c, api_key="test-key", default_model="test-model", enabled=True)

    class Related:
        def invoke(self, messages):
            assert "related_evidence" in messages[0][1]
            assert "직접 근거와 유용한 관련 근거가 모두 없을 때만" in messages[0][1]
            return SimpleNamespace(content=json.dumps(output))

    monkeypatch.setattr(c.app.state.answer.factory, "create", lambda *_: Related())
    response = c.post("/api/rag/prompts/test", json={"case": "related"})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "related_evidence"
    assert response.json()["result"]["citations"] == ["sample-1"]
