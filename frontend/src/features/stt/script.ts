import type { Utterance } from "./api";

export type PlaybackRange = Pick<
  Utterance,
  "utterance_id" | "start_ms" | "end_ms"
>;

export type ScriptBlock = PlaybackRange & {
  speaker_id: string | null;
  text: string;
  utterances: Utterance[];
  includesUnknown: boolean;
};

const MAX_GAP_MS = 3000;
const MAX_UNKNOWN_MS = 2000;

function continuous(left: Utterance, right: Utterance) {
  return (
    !left.overlap &&
    !right.overlap &&
    right.start_ms >= left.end_ms &&
    right.start_ms - left.end_ms <= MAX_GAP_MS
  );
}

// This is a presentation-only grouping. Original text and speaker assignments
// remain available for editing/export, including any inferred unknown bridge.
export function buildScript(utterances: Utterance[]): ScriptBlock[] {
  const sorted = [...utterances].sort((a, b) => a.start_ms - b.start_ms);
  const speakers = sorted.map((u) => u.speaker_id);
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i].speaker_id) continue;
    const start = i;
    while (i + 1 < sorted.length && !sorted[i + 1].speaker_id) i++;
    const previous = sorted[start - 1];
    const next = sorted[i + 1];
    const unknown = sorted.slice(start, i + 1);
    if (
      previous?.speaker_id &&
      next?.speaker_id === previous.speaker_id &&
      sorted[i].end_ms - sorted[start].start_ms <= MAX_UNKNOWN_MS &&
      unknown.every((u) => !u.manual_fields.includes("speaker_id")) &&
      [...unknown, next].every((u, index) =>
        continuous(index === 0 ? previous : unknown[index - 1], u),
      )
    ) {
      for (let j = start; j <= i; j++) speakers[j] = previous.speaker_id;
    }
  }

  const blocks: ScriptBlock[] = [];
  sorted.forEach((u, index) => {
    const last = blocks.at(-1);
    if (
      last &&
      last.speaker_id === speakers[index] &&
      continuous(sorted[index - 1], u)
    ) {
      last.end_ms = u.end_ms;
      last.utterances.push(u);
      last.text = [last.text, u.text.trim()].filter(Boolean).join(" ");
      last.includesUnknown ||= !u.speaker_id && !!last.speaker_id;
    } else {
      blocks.push({
        utterance_id: u.utterance_id,
        start_ms: u.start_ms,
        end_ms: u.end_ms,
        speaker_id: speakers[index],
        text: u.text.trim(),
        utterances: [u],
        includesUnknown: !u.speaker_id && !!speakers[index],
      });
    }
  });
  return blocks;
}

export function activeRangeId(ranges: PlaybackRange[], playbackMs: number) {
  return ranges.find((u) => playbackMs >= u.start_ms && playbackMs < u.end_ms)
    ?.utterance_id;
}
