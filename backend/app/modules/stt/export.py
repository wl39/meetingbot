import json
from typing import Literal

ExportFormat = Literal["txt", "srt", "json"]
ExportView = Literal["utterance", "script"]

MAX_GAP_MS = 3000
MAX_UNKNOWN_MS = 2000
PREVIEW_ITEMS = 2
PREVIEW_TEXT_CHARS = 240


def _continuous(left, right):
    return (
        not left["overlap"] and not right["overlap"] and 0 <= right["start_ms"] - left["end_ms"] <= MAX_GAP_MS
    )


def build_script(utterances):
    """Mirror frontend buildScript without changing source speaker assignments."""
    ordered = sorted(utterances, key=lambda u: u["start_ms"])
    speakers = [u["speaker_id"] for u in ordered]
    i = 0
    while i < len(ordered):
        if ordered[i]["speaker_id"]:
            i += 1
            continue
        start = i
        while i + 1 < len(ordered) and not ordered[i + 1]["speaker_id"]:
            i += 1
        previous = ordered[start - 1] if start else None
        following = ordered[i + 1] if i + 1 < len(ordered) else None
        unknown = ordered[start : i + 1]
        if (
            previous
            and previous["speaker_id"]
            and following
            and following["speaker_id"] == previous["speaker_id"]
            and ordered[i]["end_ms"] - ordered[start]["start_ms"] <= MAX_UNKNOWN_MS
            and all("speaker_id" not in u.get("manual_fields", []) for u in unknown)
            and all(
                _continuous(left, right) for left, right in zip([previous, *unknown], [*unknown, following])
            )
        ):
            speakers[start : i + 1] = [previous["speaker_id"]] * len(unknown)
        i += 1

    blocks = []
    for index, u in enumerate(ordered):
        speaker_id = speakers[index]
        includes_unknown = not u["speaker_id"] and bool(speaker_id)
        if blocks and blocks[-1]["speaker_id"] == speaker_id and _continuous(ordered[index - 1], u):
            last = blocks[-1]
            last["end_ms"] = u["end_ms"]
            last["source_utterance_ids"].append(u["utterance_id"])
            last["text"] = " ".join(text for text in [last["text"], u["text"].strip()] if text)
            last["includesUnknown"] = last["includesUnknown"] or includes_unknown
        else:
            blocks.append(
                {
                    "utterance_id": u["utterance_id"],
                    "start_ms": u["start_ms"],
                    "end_ms": u["end_ms"],
                    "speaker_id": speaker_id,
                    "text": u["text"].strip(),
                    "source_utterance_ids": [u["utterance_id"]],
                    "includesUnknown": includes_unknown,
                    "overlap": u["overlap"],
                }
            )
    return blocks


def _items(session, view):
    utterances = [u for u in session["utterances"] if u["status"] != "retracted"]
    if view == "script":
        return [
            {**block, "speaker_name": session["speakers"].get(block["speaker_id"], "화자 미확정")}
            for block in build_script(utterances)
        ]
    return utterances


def timestamp(ms):
    seconds, millis = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"


def _format_text(session, format, items):
    lines = []
    for i, u in enumerate(items, 1):
        speaker = session["speakers"].get(u["speaker_id"], "화자 미확정")
        marker = " [겹친 발화]" if u["overlap"] else ""
        if u.get("includesUnknown"):
            marker += " [미확정 발화 포함]"
        if format == "srt":
            lines.append(
                f"{i}\n{timestamp(u['start_ms'])} --> {timestamp(u['end_ms'])}\n[{speaker}]{marker} {u['text']}\n"
            )
        else:
            lines.append(
                f"{timestamp(u['start_ms'])}–{timestamp(u['end_ms'])} {speaker}{marker}\n{u['text']}\n"
            )
    return "\n".join(lines)


def export(session, format: ExportFormat, events, view: ExportView = "utterance"):
    items = _items(session, view)
    if format == "json":
        payload = {**session, "events": events}
        if view == "script":
            payload.update(export_view=view, script_blocks=items)
        return json.dumps(payload, ensure_ascii=False, indent=2), "application/json"
    return _format_text(session, format, items), "text/plain; charset=utf-8"


def preview(session, format: ExportFormat, view: ExportView = "utterance"):
    items = _items(session, view)
    # Keep excerpts bounded even if a script block spans a very long conversation.
    selected = [
        {
            **item,
            "text": (
                item["text"][: PREVIEW_TEXT_CHARS - 1] + "…"
                if len(item["text"]) > PREVIEW_TEXT_CHARS
                else item["text"]
            ),
        }
        for item in items[:PREVIEW_ITEMS]
    ]
    if format == "json":
        fields = ("text", "speaker_name", "speaker_id", "start_ms", "end_ms", "utterance_id", "overlap")
        if view == "script":
            fields += ("includesUnknown",)
        excerpt = [{key: item[key] for key in fields if key in item} for item in selected]
        content = json.dumps(
            {"export_view": view, "script_blocks" if view == "script" else "utterances": excerpt},
            ensure_ascii=False,
            indent=2,
        )
    else:
        content = _format_text(session, format, selected)
    return {"content": content, "total_items": len(items), "preview_items": len(selected)}
