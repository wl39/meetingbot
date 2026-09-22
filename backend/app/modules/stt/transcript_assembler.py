from difflib import SequenceMatcher

from app.contracts.utterance import UtteranceEvent, WordTiming


def merge_words(previous, incoming, start, end, stable_before):
    """Timestamp-constrained token alignment; repeated speech at distinct times stays distinct."""
    frozen = [w for w in previous if w.end <= start]
    old = [w for w in previous if w.end > start and w.start < end]
    new = sorted(incoming, key=lambda w: (w.start, w.end))
    matches = SequenceMatcher(
        None, [w.text.strip() for w in old], [w.text.strip() for w in new], autojunk=False
    )
    for block in matches.get_matching_blocks():
        for k in range(block.size):
            a, b = old[block.a + k], new[block.b + k]
            if abs((a.start + a.end) - (b.start + b.end)) < 0.6 and a.end <= stable_before:
                new[block.b + k] = a
    # Only replace the mutable window; an inference cannot rewrite earlier committed audio.
    committed = [w for w in old if w.end <= stable_before]
    new = [w for w in new if w.end > stable_before]
    tail = [w for w in previous if w.start >= end]
    return sorted(frozen + committed + new + tail, key=lambda w: (w.start, w.end))


def assemble(session_id, mode, words, turns, overlaps=(), stable_ms=None, final=False, boundaries=()):
    result = []
    ordered_turns = sorted(turns, key=lambda t: t.start)
    ordered_overlaps = sorted(overlaps)
    active_turns, active_overlaps = [], []
    turn_index = overlap_index = 0
    for word in sorted(words, key=lambda w: (w.start, w.end)):
        if not word.text.strip() or word.end <= word.start:
            continue
        scores = {}
        while turn_index < len(ordered_turns) and ordered_turns[turn_index].start < word.end:
            active_turns.append(ordered_turns[turn_index])
            turn_index += 1
        active_turns = [turn for turn in active_turns if turn.end > word.start]
        for turn in active_turns:
            amount = max(0, min(word.end, turn.end) - max(word.start, turn.start))
            scores[turn.speaker] = scores.get(turn.speaker, 0) + amount
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
        while overlap_index < len(ordered_overlaps) and ordered_overlaps[overlap_index][0] < word.end:
            active_overlaps.append(ordered_overlaps[overlap_index])
            overlap_index += 1
        active_overlaps = [(a, b) for a, b in active_overlaps if b > word.start]
        overlapping = any(a < word.end for a, _ in active_overlaps)
        speaker = None
        if ranked and ranked[0][1] / (word.end - word.start) >= 0.5:
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1] * 1.5:
                speaker = ranked[0][0]
        status = "stable" if stable_ms is None or word.end * 1000 <= stable_ms else "partial"
        speaker_status = ("assigned" if final else "provisional") if speaker else "unknown"
        start, end = max(0, round(word.start * 1000)), max(0, round(word.end * 1000))
        if end <= start:
            continue
        timing = WordTiming(text=word.text, start_ms=start, end_ms=end)
        if (
            result
            and result[-1].speaker_id == speaker
            and result[-1].status == status
            and result[-1].overlap == overlapping
            and start - result[-1].end_ms < 900
            and not any(result[-1].start_ms < boundary <= start for boundary in boundaries)
            and end - result[-1].start_ms < 10000
        ):
            result[-1].text += word.text
            result[-1].end_ms = end
            result[-1].words.append(timing)
        else:
            result.append(
                UtteranceEvent(
                    session_id=session_id,
                    input_mode=mode,
                    text=word.text,
                    words=[timing],
                    start_ms=start,
                    end_ms=end,
                    speaker_id=speaker,
                    speaker_status=speaker_status,
                    overlap=overlapping,
                    status=status,
                )
            )
    for event in result:
        event.text = event.text.strip()
    return result
