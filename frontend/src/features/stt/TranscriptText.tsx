import { Fragment, memo, useMemo } from "react";
import { time, type Utterance } from "./api";
import type { PlaybackRange } from "./script";
import { currentWord, wordRanges } from "./word-timing";

export const TranscriptText = memo(function TranscriptText({
  utterance,
  playbackMs,
  trim = false,
  onSeek,
}: {
  utterance: Utterance;
  playbackMs: number;
  trim?: boolean;
  onSeek?: (range: PlaybackRange) => void;
}) {
  const ranges = useMemo(() => wordRanges(utterance), [utterance]);
  const active = currentWord(ranges, playbackMs);
  const text = utterance.text;
  if (onSeek && ranges.length) {
    return (
      <>
        {ranges.map((range, index) => {
          const before = text.slice(
            index ? ranges[index - 1].end : 0,
            range.start,
          );
          const word = text.slice(range.start, range.end);
          return (
            <Fragment key={range.start}>
              {trim && !index ? before.trimStart() : before}
              <button
                type="button"
                className={`transcript-word ${range === active ? "current-word" : ""}`}
                aria-current={range === active ? "true" : undefined}
                aria-label={`${word} · ${time(range.start_ms)}부터 재생`}
                title={`${time(range.start_ms)}부터 재생`}
                onClick={(event) => {
                  event.stopPropagation();
                  onSeek({
                    utterance_id: utterance.utterance_id,
                    start_ms: range.start_ms,
                    end_ms: range.end_ms,
                  });
                }}
              >
                {word}
              </button>
            </Fragment>
          );
        })}
        {trim
          ? text.slice(ranges.at(-1)!.end).trimEnd()
          : text.slice(ranges.at(-1)!.end)}
      </>
    );
  }
  if (!active) return <>{trim ? text.trim() : text}</>;
  const before = text.slice(0, active.start);
  const after = text.slice(active.end);
  return (
    <>
      {trim ? before.trimStart() : before}
      <mark className="current-word" aria-current="true">
        {text.slice(active.start, active.end)}
      </mark>
      {trim ? after.trimEnd() : after}
    </>
  );
});
