import { describe, it, expect } from "vitest";
import { addPeaks, visibleRange, playerTime } from "./waveform";

describe("local waveform peaks", () => {
  it("keeps opposite-phase stereo audible and uses the largest channel peak", () => {
    const peaks = new Float32Array(2);
    addPeaks(
      peaks,
      new Float32Array([0.25, -0.25, -0.75, 0.5]),
      2,
      100,
      10,
      10,
    );
    expect([...peaks]).toEqual([0.25, 0.75]);
  });
  it("clips decoder preroll and samples after the requested tile", () => {
    const peaks = new Float32Array(2);
    addPeaks(peaks, new Float32Array([1, 0.25, 0.5, 1]), 1, 100, 9.99, 10);
    expect([...peaks]).toEqual([0.25, 0.5]);
  });
  it("retains real silence without generating artificial peaks", () => {
    const peaks = new Float32Array(100);
    addPeaks(peaks, new Float32Array(48000), 1, 48000, 0, 0);
    expect(peaks.every((value) => value === 0)).toBe(true);
  });
  it("combines multiple codec packets into the same time bin", () => {
    const peaks = new Float32Array(2);
    addPeaks(peaks, new Float32Array([0.25, 0.5]), 1, 200, 0, 0);
    addPeaks(peaks, new Float32Array([0.75, 0.125]), 1, 200, 0.01, 0);
    expect([...peaks]).toEqual([0.5, 0.75]);
  });
});

describe("long recording navigation", () => {
  it("limits decoding to the visible section and clamps recording boundaries", () => {
    expect(visibleRange(9000, 12, 18000)).toEqual({ start: 8994, end: 9006 });
    expect(visibleRange(0, 12, 18000)).toEqual({ start: 0, end: 6 });
    expect(visibleRange(18000, 12, 18000)).toEqual({
      start: 17994,
      end: 18000,
    });
  });
  it("formats up to five hours without wrapping the clock", () => {
    expect(playerTime(4252.12)).toBe("1:10:52.12");
    expect(playerTime(18000)).toBe("5:00:00.00");
  });
});
