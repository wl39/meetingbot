import copy
import json

import pytest
from fastapi.testclient import TestClient
from test_api import FakeWorkers

from app.contracts.utterance import UtteranceEvent
from app.main import create_app
from app.modules.stt.export import build_script, export, preview
from app.modules.stt.settings import Settings


def utterance(uid, start, end, speaker="a", text=None, **extra):
    return UtteranceEvent(
        session_id="session",
        utterance_id=uid,
        start_ms=start,
        end_ms=end,
        speaker_id=speaker,
        text=text if text is not None else uid,
        input_mode="file",
        **extra,
    ).model_dump()


@pytest.fixture
def session():
    return {
        "id": "session",
        "speakers": {"a": "진행자", "b": "참석자"},
        "utterances": [
            utterance("first", 0, 1000, text=" 안녕하세요. "),
            utterance("bridge", 1100, 1300, speaker=None, text="잠깐요."),
            utterance("last", 1400, 2000, text="시작할게요."),
            utterance("other", 2200, 3000, speaker="b", text="네, 좋아요.", overlap=True),
            utterance("removed", 3100, 3500, text="삭제된 발화", status="retracted"),
        ],
    }


@pytest.mark.parametrize("format", ["txt", "srt", "json"])
@pytest.mark.parametrize("view", ["utterance", "script"])
def test_exports_preserve_sources_and_select_requested_view(session, format, view):
    events = [{"type": "correction", "text": "이전 내용"}]
    original = copy.deepcopy(session)
    data, content_type = export(session, format, events, view)
    assert session == original
    if format == "json":
        result = json.loads(data)
        assert content_type == "application/json"
        assert result["utterances"] == session["utterances"]
        assert result["events"] == events
        if view == "utterance":
            assert result == {**session, "events": events}
        else:
            assert result["export_view"] == "script"
            blocks = result["script_blocks"]
            assert len(blocks) == 2
            assert blocks[0] == {
                "utterance_id": "first",
                "start_ms": 0,
                "end_ms": 2000,
                "speaker_id": "a",
                "speaker_name": "진행자",
                "text": "안녕하세요. 잠깐요. 시작할게요.",
                "source_utterance_ids": ["first", "bridge", "last"],
                "includesUnknown": True,
                "overlap": False,
            }
            assert blocks[1]["overlap"] is True
    else:
        assert content_type == "text/plain; charset=utf-8"
        assert "삭제된 발화" not in data
        assert "참석자" in data and "[겹친 발화]" in data
        if view == "script":
            assert "안녕하세요. 잠깐요. 시작할게요." in data
            assert "[미확정 발화 포함]" in data
            assert (
                "00:00:00,000 --> 00:00:02,000" in data
                if format == "srt"
                else ("00:00:00,000–00:00:02,000" in data)
            )
        else:
            assert "화자 미확정" in data
            assert "안녕하세요. 잠깐요. 시작할게요." not in data
            assert data.count("진행자") == 2


def test_default_export_keeps_existing_utterance_contract(session):
    for format in ("txt", "srt", "json"):
        assert export(session, format, []) == export(session, format, [], "utterance")


@pytest.mark.parametrize(
    ("utterances", "expected"),
    [
        ([utterance("a", 0, 1000), utterance("b", 4000, 5000)], [["a", "b"]]),
        ([utterance("a", 0, 1000), utterance("b", 4001, 5000)], [["a"], ["b"]]),
        ([utterance("b", 1000, 2000), utterance("a", 0, 1000)], [["a", "b"]]),
        ([utterance("a", 0, 1000), utterance("b", 1000, 2000, speaker="b")], [["a"], ["b"]]),
        ([utterance("a", 0, 1000), utterance("b", 900, 2000)], [["a"], ["b"]]),
        ([utterance("a", 0, 1000, overlap=True), utterance("b", 1000, 2000)], [["a"], ["b"]]),
        ([utterance("a", 0, 1000), utterance("b", 1000, 2000, overlap=True)], [["a"], ["b"]]),
        ([utterance("a", 0, 1000), utterance("b", 0, 1000)], [["a"], ["b"]]),
        ([utterance("a", 0, 1000, None), utterance("b", 1000, 2000, None)], [["a", "b"]]),
        ([], []),
    ],
)
def test_script_continuity_and_stable_sorting(utterances, expected):
    original = copy.deepcopy(utterances)
    assert [block["source_utterance_ids"] for block in build_script(utterances)] == expected
    assert utterances == original


@pytest.mark.parametrize(
    ("unknown", "before", "after", "bridged"),
    [
        ([utterance("u", 1000, 3000, None)], {}, {}, True),
        ([utterance("u", 1000, 3001, None)], {}, {"start_ms": 3001}, False),
        ([utterance("u", 1000, 1500, None), utterance("v", 2500, 3000, None)], {}, {}, True),
        ([utterance("u", 1000, 1500, None, manual_fields=["speaker_id"])], {}, {}, False),
        ([utterance("u", 1000, 1500, None, manual_fields=["text"])], {}, {}, True),
        ([utterance("u", 1000, 1500, None, overlap=True)], {}, {}, False),
        ([utterance("u", 1000, 1500, None)], {"overlap": True}, {}, False),
        ([utterance("u", 1000, 1500, None)], {}, {"overlap": True}, False),
        ([utterance("u", 1000, 1500, None)], {}, {"speaker_id": "b"}, False),
        ([utterance("u", 1000, 1500, None)], {}, {"start_ms": 4501, "end_ms": 5000}, False),
        ([utterance("u", 4001, 4500, None)], {}, {"start_ms": 4500, "end_ms": 5000}, False),
        ([utterance("u", 900, 1500, None)], {}, {}, False),
        ([utterance("u", 1000, 1500, None)], {}, {"start_ms": 1400}, False),
        ([utterance("u", 1000, 2000, None), utterance("v", 1500, 2500, None)], {}, {}, False),
    ],
)
def test_unknown_bridge_requires_matching_speakers_short_duration_and_continuity(
    unknown, before, after, bridged
):
    source = [
        {**utterance("first", 0, 1000), **before},
        *unknown,
        {**utterance("last", 3000, 4000), **after},
    ]
    original = copy.deepcopy(source)
    result = build_script(source)
    assert source == original
    assert any(block["includesUnknown"] for block in result) is bridged
    if bridged:
        assert len(result) == 1
        assert result[0]["speaker_id"] == "a"
    else:
        assert any(block["speaker_id"] is None for block in result)


@pytest.mark.parametrize("unknown_first", [True, False])
def test_unknown_at_conversation_edge_stays_unknown(unknown_first):
    source = [
        utterance("first", 0, 1000, speaker=None if unknown_first else "a"),
        utterance("last", 1000, 2000, speaker="a" if unknown_first else None),
    ]
    result = build_script(source)
    assert len(result) == 2
    assert not any(block["includesUnknown"] for block in result)


def test_script_joins_trimmed_text_without_extra_spaces():
    source = [utterance("a", 0, 1000, text="  안녕  "), utterance("b", 1000, 2000, text="   ")]
    assert build_script(source)[0]["text"] == "안녕"


@pytest.mark.parametrize("format", ["txt", "srt", "json"])
@pytest.mark.parametrize("view", ["utterance", "script"])
def test_preview_uses_selected_view_and_bounds_excerpt(session, format, view):
    session["utterances"][0]["text"] = "안" * 1000
    session["utterances"][0]["words"] = [{"text": "WORD_ARRAY_MUST_NOT_LEAK"}] * 1000
    session["environment"] = {"detail": "SESSION_METADATA_MUST_NOT_LEAK"}
    session["utterances"].append(utterance("extra", 5000, 6000, speaker="b", text="AFTER_PREVIEW"))
    original = copy.deepcopy(session)
    result = preview(session, format, view)
    assert session == original
    assert result["total_items"] == (3 if view == "script" else 5)
    assert result["preview_items"] == 2
    assert "안" * 239 + "…" in result["content"]
    assert "안" * 240 not in result["content"]
    assert "WORD_ARRAY_MUST_NOT_LEAK" not in result["content"]
    assert "SESSION_METADATA_MUST_NOT_LEAK" not in result["content"]
    assert "AFTER_PREVIEW" not in result["content"]
    assert len(result["content"]) < 1500
    if format == "json":
        excerpt = json.loads(result["content"])
        key = "script_blocks" if view == "script" else "utterances"
        assert set(excerpt) == {"export_view", key}
        assert len(excerpt[key]) == 2
        assert len(excerpt[key][0]["text"]) == 240
    else:
        visible = [u for u in session["utterances"] if u["status"] != "retracted"]
        chosen = build_script(visible)[:2] if view == "script" else visible[:2]
        subset = {**session, "utterances": [{**u, "status": "stable"} for u in chosen]}
        for item in subset["utterances"]:
            if len(item["text"]) > 240:
                item["text"] = item["text"][:239] + "…"
        assert result["content"] == export(subset, format, [])[0]


@pytest.mark.parametrize("format", ["txt", "srt", "json"])
@pytest.mark.parametrize("view", ["utterance", "script"])
def test_empty_exports_and_previews(format, view):
    session = {"speakers": {}, "utterances": []}
    result = preview(session, format, view)
    assert result["total_items"] == result["preview_items"] == 0
    exported, _ = export(session, format, [], view)
    if format == "json":
        assert json.loads(exported)["utterances"] == []
        assert json.loads(result["content"])["script_blocks" if view == "script" else "utterances"] == []
    else:
        assert exported == result["content"] == ""


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(engine="fake", data_dir=tmp_path), FakeWorkers)
    with TestClient(app) as client:
        client.headers["Authorization"] = "Bearer " + app.state.token
        yield client


@pytest.mark.parametrize("format", ["txt", "srt", "json"])
@pytest.mark.parametrize("view", ["utterance", "script"])
def test_export_and_preview_endpoints(client, session, format, view):
    saved = client.post("/api/stt/sessions", json={}).json()
    saved.update(speakers=session["speakers"], utterances=session["utterances"])
    client.app.state.service.repo.save(saved)
    sid = saved["id"]
    query = f"format={format}&view={view}"
    response = client.get(f"/api/stt/sessions/{sid}/export?{query}")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == f'attachment; filename="{sid}.{format}"'
    assert response.text == export(saved, format, [], view)[0]
    response = client.get(f"/api/stt/sessions/{sid}/export/preview?{query}")
    assert response.status_code == 200
    assert response.json() == preview(saved, format, view)
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("route", ["export", "export/preview"])
def test_export_endpoints_validate_view_format_session_and_authorization(client, route):
    sid = client.post("/api/stt/sessions", json={}).json()["id"]
    path = f"/api/stt/sessions/{sid}/{route}"
    assert client.get(path + "?view=invalid").status_code == 422
    assert client.get(path + "?format=csv").status_code == 422
    assert client.get(path, headers={"Authorization": ""}).status_code == 401
    assert client.get(f"/api/stt/sessions/missing/{route}").status_code == 404
