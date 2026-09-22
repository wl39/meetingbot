import json
import sqlite3
import time
from pathlib import Path

from conftest import ask, wait_question
from meetingbot_access import COOKIE, GUEST_SESSION_SECONDS

from meetingbot_rag.db import SCHEMA, Database, dumps, uid
from meetingbot_rag.sources import RagError


def setup(client, monkeypatch):
    c, _, core = client
    ws = core.workspaces.create("공유 자료", "질문 기록 검증")
    alice = c.app.state.access.issue_key("앨리스", "visitor")
    bob = c.app.state.access.issue_key("밥", "visitor")
    admin = c.app.state.access.issue_key("자료 관리자", "admin")

    def answer(wid, query, **_):
        return {
            "request_id": uid(),
            "workspace_id": wid,
            "revision_id": None,
            "query": query,
            "status": "answered",
            "answer": "저장된 답변: " + query,
            "evidence": [],
            "citations": [],
            "timings_ms": {},
        }

    monkeypatch.setattr(c.app.state.answer, "answer", answer)
    monkeypatch.setattr(core.retrieval, "search", answer)
    return c, core, ws["id"], alice, bob, admin


def headers(account):
    return {"Authorization": "Bearer " + account["key"]}


def test_personal_history_isolated_and_admin_filterable(client, monkeypatch):
    c, core, wid, alice, bob, admin = setup(client, monkeypatch)
    a = ask(c, f"/api/rag/workspaces/{wid}/questions", headers=headers(alice), json={"query": "앨리스 질문"})
    b = ask(c, f"/api/rag/workspaces/{wid}/questions", headers=headers(bob), json={"query": "밥 질문"})
    search = c.post(
        f"/api/rag/workspaces/{wid}/search", headers=headers(alice), json={"query": "검색 기록"}
    ).json()
    own = c.get("/api/rag/history", headers=headers(alice)).json()
    assert own["total"] == 2
    assert {r["id"] for r in own["items"]} == {a["request_id"], search["request_id"]}
    assert all(r["subject"] == alice["id"] and r["account_label"] == "앨리스" for r in own["items"])
    assert "result" not in own["items"][0]  # List pages do not return full document evidence.
    assert len(c.get(f"/api/rag/workspaces/{wid}/questions", headers=headers(alice)).json()) == 2
    for path in ("/history?scope=all", "/history/filters?scope=all", f"/history/{b['request_id']}?scope=all"):
        assert c.get("/api/rag" + path, headers=headers(alice)).status_code == 403
    assert c.get(f"/api/rag/history/{b['request_id']}", headers=headers(alice)).status_code == 404
    assert c.get("/api/rag/history?subject=" + bob["id"], headers=headers(alice)).json()["total"] == 2
    all_records = c.get("/api/rag/history?scope=all", headers=headers(admin)).json()
    assert all_records["total"] == 3
    filtered = c.get(
        "/api/rag/history",
        headers=headers(admin),
        params={
            "scope": "all",
            "subject": alice["id"],
            "workspace_id": wid,
            "kind": "question",
            "q": "저장된 답변",
        },
    ).json()
    assert [r["id"] for r in filtered["items"]] == [a["request_id"]]
    assert (
        c.get("/api/rag/history?scope=all&limit=1&offset=1", headers=headers(admin)).json()["items"][0]["id"]
        == b["request_id"]
    )
    assert (
        c.get("/api/rag/history?scope=all&since=" + str(time.time() + 10), headers=headers(admin)).json()[
            "total"
        ]
        == 0
    )
    filters = c.get("/api/rag/history/filters?scope=all", headers=headers(admin)).json()
    assert {x["subject"] for x in filters["accounts"]} == {alice["id"], bob["id"]}
    assert filters["workspaces"] == [{"id": wid, "name": "공유 자료"}]
    detail = c.get(f"/api/rag/history/{a['request_id']}?scope=all", headers=headers(admin)).json()
    assert detail["result"]["answer"] == a["answer"] and detail["created_at"] == a["created_at"]
    # Persisted identity is recovered by another browser logging in with the same account.
    login = c.post("/api/rag/auth/login", headers={"Authorization": ""}, json={"key": alice["key"]})
    assert login.status_code == 200
    assert c.get("/api/rag/history", headers={"Authorization": ""}).json()["total"] == 2
    db = Database(core.s.data_dir / "registry.sqlite")
    assert db.one("SELECT subject FROM query_runs WHERE id=?", (a["request_id"],))["subject"] == alice["id"]
    db.close()


def test_failures_and_interrupted_requests_remain_in_history(client, monkeypatch):
    c, core, wid, alice, _, _ = setup(client, monkeypatch)

    def fail(*args, **kwargs):
        row = core.db.one("SELECT * FROM query_runs ORDER BY created_at DESC LIMIT 1")
        assert row["subject"] == alice["id"]
        assert json.loads(row["result"])["status"] == "processing"
        raise RagError("MODEL_NOT_READY", "자료 검색 준비 중", 503)

    monkeypatch.setattr(c.app.state.answer, "answer", fail)
    response = c.post(
        f"/api/rag/workspaces/{wid}/questions", headers=headers(alice), json={"query": "실패한 질문"}
    )
    assert response.status_code == 202
    assert wait_question(c, response, headers(alice))["status"] == "failed"
    page = c.get("/api/rag/history", headers=headers(alice)).json()
    assert page["items"][0]["status"] == "failed"
    record_id = page["items"][0]["id"]
    core.db.execute(
        "UPDATE query_runs SET input=NULL,result=json_set(result,'$.status','processing') WHERE id=?", (record_id,)
    )
    core.db.recover()
    result = c.get(f"/api/rag/history/{record_id}", headers=headers(alice)).json()["result"]
    assert result["status"] == "failed" and result["reason"] == "SERVER_RESTARTED"


def test_legacy_records_are_admin_only_and_retention_still_applies(client, monkeypatch):
    c, core, wid, alice, _, admin = setup(client, monkeypatch)
    legacy, expired = uid(), uid()
    for rid, created in ((legacy, time.time()), (expired, time.time() - 31 * 86400)):
        core.db.execute(
            "INSERT INTO query_runs(id,workspace_id,created_at,result) VALUES(?,?,?,?)",
            (rid, wid, created, dumps({"query": "이전 질문", "status": "answered", "evidence": []})),
        )
    assert c.get("/api/rag/history", headers=headers(alice)).json()["total"] == 0
    assert c.get(f"/api/rag/history/{legacy}", headers=headers(alice)).status_code == 404
    rows = c.get("/api/rag/history?scope=all&subject=legacy", headers=headers(admin)).json()["items"]
    assert len(rows) == 1 and rows[0]["subject"] is None
    assert c.get(f"/api/rag/history/{expired}?scope=all", headers=headers(admin)).status_code == 404


def test_guest_identity_survives_browser_return_and_is_separate(client):
    c, _, _ = client
    response = c.get("/api/rag/auth/session", headers={"Authorization": ""})
    account = response.json()["account"]
    token = c.cookies.get(COOKIE)
    assert account["id"].startswith("guest_")
    assert "HttpOnly" in response.headers["set-cookie"]
    assert f"Max-Age={GUEST_SESSION_SECONDS}" in response.headers["set-cookie"]
    assert c.get("/api/rag/auth/session", headers={"Authorization": ""}).json()["account"] == account
    assert c.app.state.access.session(token, allow_guest=True).subject == account["id"]
    c.cookies.clear()
    other = c.get("/api/rag/auth/session", headers={"Authorization": ""}).json()["account"]
    assert other["id"] != account["id"]


def test_history_respects_revoked_sources(client, monkeypatch):
    c, core, _, alice, _, admin = setup(client, monkeypatch)
    ws = core.workspaces.create("연결된 자료", "", "docs")
    entry = ask(c, f"/api/rag/workspaces/{ws['id']}/questions", headers=headers(alice), json={"query": "비공개 질문"})

    def revoked(*_):
        raise RagError("SOURCE_REVOKED", "자료 접근이 회수되었습니다.", 403)

    monkeypatch.setattr(core.sources, "validate_source", revoked)
    for account, scope in ((alice, "mine"), (admin, "all")):
        params = {"scope": scope}
        assert c.get("/api/rag/history", params=params, headers=headers(account)).json()["total"] == 0
        assert (
            c.get("/api/rag/history/filters", params=params, headers=headers(account)).json()["workspaces"]
            == []
        )
        assert (
            c.get(
                f"/api/rag/history/{entry['request_id']}", params=params, headers=headers(account)
            ).status_code
            == 404
        )


def test_history_migration_preserves_legacy_answers_without_guessing_owner(tmp_path):
    path = tmp_path / "v7.sqlite"
    migration_dir = Path(__file__).parents[1] / "meetingbot_rag/migrations"
    raw = dumps({"query": "이전 질문", "answer": "이전 답변", "status": "answered"})
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
        for migration in sorted(migration_dir.glob("00[2-7]_*.sql")):
            db.executescript(migration.read_text())
        db.execute("INSERT INTO workspaces VALUES('keep','기존 자료','',1,NULL,0)")
        db.execute("INSERT INTO query_runs VALUES('question','keep',NULL,1,?)", (raw,))
    db = Database(path)
    entry = db.one("SELECT * FROM query_runs WHERE id='question'")
    assert entry["result"] == raw and entry["workspace_name"] == "기존 자료"
    assert entry["subject"] is None and entry["account_label"] is None
    assert entry["kind"] == "question"
    db.close()
