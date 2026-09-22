import { describe, expect, it } from "vitest";
import type { Utterance } from "./api";
import { currentWord, wordRanges } from "./word-timing";

const utterance = (overrides: Partial<Utterance> = {}): Utterance => ({
  utterance_id: "u",
  revision: 1,
  start_ms: 1000,
  end_ms: 4000,
  text: "안녕하세요,  여러분!",
  speaker_id: "A",
  status: "stable",
  speaker_status: "assigned",
  overlap: false,
  manual_fields: [],
  words: [
    { text: " 안녕", start_ms: 1000, end_ms: 1200 },
    { text: "하세요,", start_ms: 1200, end_ms: 1800 },
    { text: " 여러분!", start_ms: 2200, end_ms: 4000 },
  ],
  ...overrides,
});

describe("word highlighting", () => {
  it("advances across displayed words when a model token contains spaces", () => {
    const u = utterance({
      text: "하나 두개",
      words: [{ text: " 하나 두개", start_ms: 1000, end_ms: 4000 }],
    });
    const ranges = wordRanges(u);
    expect(currentWord(ranges, 1200)?.start).toBe(0);
    expect(currentWord(ranges, 2500)?.start).toBe(3);
    expect(ranges[0].end_ms).toBe(ranges[1].start_ms);
  });
  it("combines Korean model fragments and preserves exact displayed text", () => {
    const u = utterance();
    const before = structuredClone(u);
    const ranges = wordRanges(u);
    expect(ranges.map((r) => u.text.slice(r.start, r.end))).toEqual([
      "안녕하세요,",
      "여러분!",
    ]);
    expect(ranges.map((r) => [r.start_ms, r.end_ms])).toEqual([
      [1000, 1800],
      [2200, 4000],
    ]);
    expect(u).toEqual(before);
  });

  it("clears during silence and at the end, and follows reverse seeks", () => {
    const ranges = wordRanges(utterance());
    for (const time of [-1, 999, 1800, 2100, 4000, NaN])
      expect(currentWord(ranges, time)).toBeUndefined();
    expect(currentWord(ranges, 1000)).toBe(ranges[0]);
    expect(currentWord(ranges, 2200)).toBe(ranges[1]);
    expect(currentWord(ranges, 1100)).toBe(ranges[0]);
  });

  it("keeps repeated words at distinct timestamps", () => {
    const u = utterance({
      text: "네 네",
      words: [
        { text: " 네", start_ms: 1000, end_ms: 1400 },
        { text: " 네", start_ms: 3000, end_ms: 4000 },
      ],
    });
    expect(currentWord(wordRanges(u), 3100)?.start).toBe(2);
  });

  it("estimates legacy and corrected text within the original utterance", () => {
    for (const u of [
      utterance({ words: undefined }),
      utterance({ manual_fields: ["text"] }),
      utterance({ text: "다른 수정 대본" }),
      utterance({
        words: [{ text: "안녕하세요, 여러분!", start_ms: NaN, end_ms: 4000 }],
      }),
    ]) {
      const ranges = wordRanges(u);
      expect(ranges[0].start_ms).toBe(1000);
      expect(ranges.at(-1)?.end_ms).toBe(4000);
      expect(currentWord(ranges, 4000)).toBeUndefined();
      expect(ranges.map((r) => u.text.slice(r.start, r.end))).toEqual(
        u.text.split(/\s+/),
      );
    }
  });

  it("preserves leading whitespace, line breaks, punctuation and emoji offsets", () => {
    const u = utterance({ text: "  네,\n 👋 좋아요!  ", words: undefined });
    const ranges = wordRanges(u);
    expect(ranges.map((r) => u.text.slice(r.start, r.end))).toEqual([
      "네,",
      "👋",
      "좋아요!",
    ]);
    expect(wordRanges(utterance({ text: "  " }))).toEqual([]);
    expect(wordRanges(utterance({ end_ms: 1000 }))).toEqual([]);
  });
});
