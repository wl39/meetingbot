import { describe, expect, it } from "vitest";
import type { Utterance } from "./api";
import { activeRangeId, buildScript } from "./script";

function u(
  id: string,
  start: number,
  end: number,
  speaker: string | null = "A",
  text = id,
): Utterance {
  return {
    utterance_id: id,
    revision: 1,
    start_ms: start,
    end_ms: end,
    speaker_id: speaker,
    text,
    status: "stable",
    speaker_status: "assigned",
    overlap: false,
    manual_fields: [],
  };
}

describe("script grouping", () => {
  it("merges the requested example including the short unknown bridge without changing source data", () => {
    const source = [
      u("1", 120100, 129900, "A", "첫 발언"),
      u("2", 131000, 140000, "A", "이렇게 해주면"),
      u("3", 140000, 141500, null, "될"),
      u("4", 141500, 146000, "A", "것 같아요."),
    ];
    const before = structuredClone(source);
    const blocks = buildScript(source);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({
      start_ms: 120100,
      end_ms: 146000,
      speaker_id: "A",
      includesUnknown: true,
      text: "첫 발언 이렇게 해주면 될 것 같아요.",
    });
    expect(source).toEqual(before);
    expect(activeRangeId(blocks, 130000)).toBe("1");
  });

  it("separates speaker changes, long pauses and overlapping speech", () => {
    const blocks = buildScript([
      u("1", 0, 1000),
      u("2", 1000, 2000, "B"),
      u("3", 2000, 3000),
      u("4", 7000, 8000),
      { ...u("5", 8000, 9000), overlap: true },
      u("6", 8500, 9500),
    ]);
    expect(blocks).toHaveLength(6);
  });

  it("does not assign unknown speech across different speakers or at the edges", () => {
    const blocks = buildScript([
      u("1", 0, 1000, null),
      u("2", 1000, 2000),
      u("3", 2000, 2500, null),
      u("4", 2500, 3000, "B"),
      u("5", 3000, 4000, null),
    ]);
    expect(blocks.map((b) => b.speaker_id)).toEqual([
      null,
      "A",
      null,
      "B",
      null,
    ]);
  });

  it("keeps long or explicitly unassigned speech separate", () => {
    for (const middle of [
      u("2", 1000, 4000, null),
      { ...u("2", 1000, 2000, null), manual_fields: ["speaker_id"] },
    ]) {
      expect(
        buildScript([u("1", 0, 1000), middle, u("3", 4000, 5000)]),
      ).toHaveLength(3);
    }
  });

  it("bridges several short unknown fragments and sorts by time", () => {
    const blocks = buildScript([
      u("4", 2500, 3000),
      u("2", 1000, 1500, null),
      u("1", 0, 1000),
      u("3", 1500, 2500, null),
    ]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0].text).toBe("1 2 3 4");
  });

  it("tracks exact playback boundaries, gaps, and reverse seeks", () => {
    const blocks = buildScript([u("1", 0, 1000), u("2", 2000, 3000, "B")]);
    expect(activeRangeId(blocks, 0)).toBe("1");
    expect(activeRangeId(blocks, 1000)).toBeUndefined();
    expect(activeRangeId(blocks, 2000)).toBe("2");
    expect(activeRangeId(blocks, 3000)).toBeUndefined();
    expect(activeRangeId(blocks, 500)).toBe("1");
    expect(buildScript([])).toEqual([]);
  });
});
