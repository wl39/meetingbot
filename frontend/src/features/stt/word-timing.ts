import type { Utterance } from "./api";

export type TimedTextRange = {
  start: number;
  end: number;
  start_ms: number;
  end_ms: number;
};

// Keep offsets in the displayed text so punctuation, spacing and edits survive.
export function wordRanges(u: Utterance): TimedTextRange[] {
  const tokens = Array.from(u.text.matchAll(/\S+/gu));
  if (!tokens.length || u.end_ms <= u.start_ms) return [];
  const words = u.words ?? [];
  const compact = (text: string) => text.replace(/\s/gu, "");
  if (
    words.length &&
    !u.manual_fields.includes("text") &&
    words.every(
      (w, i) =>
        compact(w.text).length > 0 &&
        Number.isFinite(w.start_ms) &&
        Number.isFinite(w.end_ms) &&
        w.start_ms >= u.start_ms &&
        w.end_ms <= u.end_ms &&
        w.end_ms > w.start_ms &&
        (!i || w.start_ms >= words[i - 1].start_ms),
    ) &&
    words.map((w) => compact(w.text)).join("") === compact(u.text)
  ) {
    let cursor = 0;
    const spans = words.map((w) => {
      const start = cursor;
      cursor += compact(w.text).length;
      return { start, end: cursor, ...w };
    });
    cursor = 0;
    let wordIndex = 0;
    return tokens.map((token) => {
      const start = cursor;
      cursor += token[0].length;
      while (spans[wordIndex].end <= start) wordIndex++;
      const first = spans[wordIndex];
      const positionTime = (span: typeof first, offset: number) =>
        span.start_ms +
        ((span.end_ms - span.start_ms) *
          (Math.min(offset, span.end) - span.start)) /
          (span.end - span.start);
      let endMs = positionTime(first, cursor);
      while (
        wordIndex + 1 < spans.length &&
        spans[wordIndex + 1].start < cursor
      ) {
        wordIndex++;
        endMs = Math.max(endMs, positionTime(spans[wordIndex], cursor));
      }
      return {
        start: token.index,
        end: token.index + token[0].length,
        start_ms: positionTime(first, start),
        end_ms: endMs,
      };
    });
  }

  // Older sessions have no word timestamps. Estimate within each utterance,
  // never across the pauses between utterances in a combined script block.
  const weights = tokens.map((token) => Array.from(token[0]).length);
  const total = weights.reduce((sum, weight) => sum + weight, 0);
  let offset = 0;
  return tokens.map((token, i) => {
    const startMs = u.start_ms + ((u.end_ms - u.start_ms) * offset) / total;
    offset += weights[i];
    return {
      start: token.index,
      end: token.index + token[0].length,
      start_ms: startMs,
      end_ms: u.start_ms + ((u.end_ms - u.start_ms) * offset) / total,
    };
  });
}

export function currentWord(ranges: TimedTextRange[], playbackMs: number) {
  return ranges.find((w) => playbackMs >= w.start_ms && playbackMs < w.end_ms);
}
