import json
import struct

import numpy as np
import pytest

from app.contracts.utterance import UtteranceEvent
from app.modules.stt.audio import PCMStream
from app.modules.stt.engines.base import Turn, Word
from app.modules.stt.export import export
from app.modules.stt.repository import Conflict, Repository
from app.modules.stt.schemas import Correction, Options
from app.modules.stt.speaker_mapper import SpeakerMapper
from app.modules.stt.transcript_assembler import assemble, merge_words


def frame(sequence, start, audio):
    return struct.pack("<IQI", sequence, start, len(audio)) + np.asarray(audio, dtype="<f4").tobytes()


def test_resampler_preserves_long_fractional_timeline():
    stream = PCMStream(44100, 300)
    outputs = [stream.push(frame(i, i * 6615, np.zeros(6615)))[0] for i in range(200)]
    outputs.append(stream.flush())
    assert sum(map(len, outputs)) == 30 * 16000


def test_gap_keeps_time_and_signals_missing_input():
    stream = PCMStream(48000, 300)
    a, _ = stream.push(frame(0, 0, np.zeros(4800)))
    b, warning = stream.push(frame(2, 9600, np.zeros(4800)))
    assert warning["missing_samples"] == 4800
    assert len(a) + len(b) + len(stream.flush()) == 4800


@pytest.mark.parametrize(
    "payload", [b"bad", frame(0, 0, [float("nan")]), frame(0, 0, [2.0]), struct.pack("<IQI", 0, 0, 3)]
)
def test_invalid_pcm_rejected(payload):
    with pytest.raises(ValueError):
        PCMStream(16000, 300).push(payload)


def test_duplicate_and_session_limit_rejected():
    stream = PCMStream(16000, 1)
    stream.push(frame(0, 0, [0.1]))
    with pytest.raises(ValueError, match="OUT_OF_ORDER"):
        stream.push(frame(0, 0, [0.1]))
    with pytest.raises(ValueError, match="SESSION_LIMIT"):
        stream.push(frame(1, 16000, [0.1]))


def test_swapped_clusters_keep_session_speaker_ids():
    mapper = SpeakerMapper()
    first = mapper.map([Turn(0, 2, "A"), Turn(2, 4, "B")])
    second = mapper.map([Turn(0, 2, "B"), Turn(2, 4, "A"), Turn(5, 7, "B")])
    assert [t.speaker for t in second] == [first[0].speaker, first[1].speaker, first[0].speaker]


def test_ambiguous_merged_cluster_does_not_invent_identity():
    mapper = SpeakerMapper()
    mapper.map([Turn(0, 2, "A"), Turn(2, 4, "B")])
    assert mapper.map([Turn(0, 4, "merged")]) == []


def test_short_evidence_stays_unknown():
    assert SpeakerMapper().map([Turn(0, 0.12, "A")]) == []


def test_speaker_changes_split_asr_sentence_and_overlap_is_visible():
    events = assemble(
        "s",
        "file",
        [Word(0, 1, "안녕"), Word(1, 2, " 하세요")],
        [Turn(0, 1, "A"), Turn(1, 2, "B")],
        [(1.5, 1.9)],
        final=True,
    )
    assert len(events) == 2
    assert events[0].speaker_id == "A"
    assert events[1].speaker_id == "B"
    assert events[1].overlap


def test_repeated_yes_at_distinct_times_survives_window_merge():
    previous = [Word(1, 1.3, " 네"), Word(2, 2.3, " 네")]
    incoming = [Word(2.02, 2.31, " 네"), Word(3, 3.3, " 네")]
    result = merge_words(previous, incoming, 1.5, 4, 1.4)
    assert len(result) == 3
    assert result[0].start == 1


def event(sid, text="첫 발언", start=0, end=1000, **kwargs):
    return UtteranceEvent(session_id=sid, input_mode="file", start_ms=start, end_ms=end, text=text, **kwargs)


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "test.sqlite3")
    yield r
    r.db.close()


def test_revision_conflict_manual_protection_and_event_idempotence(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    repo.publish(sid, 1, [event(sid)])
    current = repo.get(sid)["utterances"][0]
    patch = Correction(base_revision=1, text="직접 수정한 발언")
    updated = repo.correct(sid, current["utterance_id"], patch)
    assert updated["revision"] == 2
    with pytest.raises(Conflict):
        repo.correct(sid, current["utterance_id"], patch)
    repo.publish(sid, 1, [event(sid, "늦게 도착한 결과")])
    assert repo.get(sid)["utterances"][0]["text"] == "직접 수정한 발언"
    repo._event(updated)
    assert len(repo.events(sid)) == 2


def test_split_emits_retraction_and_replacement_ids(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    repo.publish(sid, 1, [event(sid, end=3000)])
    old = repo.get(sid)["utterances"][0]["utterance_id"]
    emitted = repo.publish(sid, 1, [event(sid, "하나", end=1500), event(sid, "둘", start=1500, end=3000)])
    assert any(e["status"] == "retracted" and e["utterance_id"] == old for e in emitted)
    assert all(old in e["replaces_utterance_ids"] for e in emitted if e["status"] != "retracted")


def test_deleted_session_cannot_be_resurrected(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    repo.delete(sid)
    assert repo.publish(sid, 1, [event(sid)]) == []
    assert repo.get(sid) is None
    assert repo.events(sid) == []


def test_stale_generation_ignored(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    s["generation"] = 2
    repo.save(s)
    assert repo.publish(sid, 1, [event(sid)]) == []


def test_export_preserves_korean_and_hour_timestamps(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    repo.publish(sid, 1, [event(sid, "네, 맞습니다.", start=3661000, end=3662000)])
    s = repo.get(sid)
    srt, _ = export(s, "srt", [])
    assert "01:01:01,000 --> 01:01:02,000" in srt
    assert "네, 맞습니다." in srt
    raw, _ = export(s, "json", repo.events(sid))
    assert json.loads(raw)["events"][0]["schema_version"] == 1


def test_restart_marks_inflight_sessions_and_jobs_interrupted(tmp_path):
    path = tmp_path / "db"
    r = Repository(path)
    s = r.create("file", Options().model_dump(), {})
    r.job("j", s["id"], "TRANSCRIBING")
    r.db.close()
    r = Repository(path)
    assert r.get(s["id"])["state"] == "INTERRUPTED"
    assert r.get_job("j")["state"] == "INTERRUPTED"
    r.db.close()


def test_controller_replay_rejects_duplicates_and_revision_inversion():
    from app.contracts.consumer import TranscriptConsumer
    from app.contracts.utterance import uid

    consumer = TranscriptConsumer()
    first = event("s")
    newer = first.model_copy(update={"event_id": uid("evt"), "revision": 3, "text": "수정"})
    assert consumer.accept(newer)
    assert not consumer.accept(newer)
    assert not consumer.accept(first)
    assert consumer.latest[("s", first.utterance_id)].text == "수정"


def test_manual_region_does_not_swallow_subsequent_speech(repo):
    s = repo.create("microphone", Options().model_dump(), {})
    sid = s["id"]
    repo.publish(sid, 1, [event(sid, "네", end=1000)])
    u = repo.get(sid)["utterances"][0]
    repo.correct(sid, u["utterance_id"], Correction(base_revision=u["revision"], text="네!"))
    words = [Word(0, 1, "네"), Word(1.1, 2, " 계속합니다.")]
    candidates = assemble(sid, "microphone", words, [], boundaries=repo.manual_boundaries(sid))
    repo.publish(sid, 1, candidates)
    assert [u["text"] for u in repo.get(sid)["utterances"]] == ["네!", "계속합니다."]


def test_text_correction_still_accepts_later_speaker_attribution(repo):
    s = repo.create("file", Options().model_dump(), {})
    sid = s["id"]
    repo.publish(sid, 1, [event(sid)])
    u = repo.get(sid)["utterances"][0]
    repo.correct(sid, u["utterance_id"], Correction(base_revision=1, text="직접 수정"))
    repo.publish(sid, 1, [event(sid, "모델 텍스트", speaker_id="spk_01", speaker_status="assigned")])
    actual = repo.get(sid)["utterances"][0]
    assert actual["text"] == "직접 수정"
    assert actual["speaker_id"] == "spk_01"
    assert actual["revision"] == 3


def test_word_times_survive_assembly_publish_and_timing_only_updates(repo):
    sid = repo.create("file", Options().model_dump(), {})["id"]
    words = [Word(1, 1.4, " 안녕"), Word(1.5, 2, "하세요"), Word(2.2, 3, " 여러분!")]
    candidates = assemble(sid, "file", words, [])
    assert candidates[0].text == "안녕하세요 여러분!"
    assert [(w.start_ms, w.end_ms) for w in candidates[0].words] == [(1000, 1400), (1500, 2000), (2200, 3000)]
    repo.publish(sid, 1, candidates)
    first = repo.get(sid)["utterances"][0]
    assert len(first["words"]) == 3
    assert repo.publish(sid, 1, assemble(sid, "file", words, [])) == []
    words[1].start = 1.6
    repo.publish(sid, 1, assemble(sid, "file", words, []))
    updated = repo.get(sid)["utterances"][0]
    assert updated["utterance_id"] == first["utterance_id"]
    assert updated["revision"] == first["revision"] + 1
    assert updated["changed_fields"] == ["words"]
    assert updated["words"][1]["start_ms"] == 1600


def test_text_correction_clears_stale_word_times_and_keeps_manual_fields(repo):
    sid = repo.create("file", Options().model_dump(), {})["id"]
    candidates = assemble(sid, "file", [Word(0, 1, "안녕하세요")], [])
    repo.publish(sid, 1, candidates)
    original = repo.get(sid)["utterances"][0]
    corrected = repo.correct(sid, original["utterance_id"], Correction(base_revision=1, text="안녕!"))
    assert corrected["words"] == []
    assert corrected["manual_fields"] == ["text"]
    assert "words" in corrected["changed_fields"]
    repo.publish(sid, 1, candidates)
    assert repo.get(sid)["utterances"][0]["words"] == []


def test_manual_speaker_keeps_and_refreshes_word_times(repo):
    sid = repo.create("file", Options().model_dump(), {})["id"]
    words = [Word(0, 0.5, "안녕"), Word(0.6, 1, "하세요")]
    repo.publish(sid, 1, assemble(sid, "file", words, []))
    original = repo.get(sid)["utterances"][0]
    corrected = repo.correct(sid, original["utterance_id"], Correction(base_revision=1, speaker_id=None))
    assert corrected["words"] == original["words"]
    words[1].start = 0.7
    repo.publish(sid, 1, assemble(sid, "file", words, []))
    updated = repo.get(sid)["utterances"][0]
    assert updated["words"][1]["start_ms"] == 700
    assert updated["speaker_id"] is None
    assert updated["revision"] == 3


def test_legacy_events_remain_readable_and_gain_word_times_on_publish(repo):
    sid = repo.create("file", Options().model_dump(), {})["id"]
    repo.publish(sid, 1, assemble(sid, "file", [Word(0, 1, "네")], []))
    session = repo.get(sid)
    del session["utterances"][0]["words"]
    repo.save(session)
    assert UtteranceEvent.model_validate(session["utterances"][0]).words == []
    repo.publish(sid, 1, assemble(sid, "file", [Word(0, 1, "네")], []))
    assert repo.get(sid)["utterances"][0]["words"] == [{"text": "네", "start_ms": 0, "end_ms": 1000}]
