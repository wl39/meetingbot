import { describe, it, expect } from "vitest";
import { packFrame } from "./audio-worklet";
describe("PCM wire contract", () => {
  it("preserves final short frames and 64-bit sample offsets", () => {
    const buffer = packFrame(19, 2 ** 33, new Float32Array([0.25, -0.5]));
    const view = new DataView(buffer);
    expect(buffer.byteLength).toBe(24);
    expect(view.getUint32(0, true)).toBe(19);
    expect(view.getBigUint64(4, true)).toBe(BigInt(2 ** 33));
    expect(view.getUint32(12, true)).toBe(2);
    expect(view.getFloat32(16, true)).toBe(0.25);
    expect(view.getFloat32(20, true)).toBe(-0.5);
  });
});

import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";
it("AudioWorklet downmixes and flushes the last short frame before the stop acknowledgement", () => {
  const messages: { type: string; samples?: Float32Array }[] = [];
  let Worklet: any;
  class Processor {
    port = {
      postMessage: (message: any) => messages.push(message),
      onmessage: null as any,
    };
  }
  runInNewContext(readFileSync("public/audio-worklet.js", "utf8"), {
    AudioWorkletProcessor: Processor,
    sampleRate: 48000,
    Float32Array,
    registerProcessor: (_name: string, processor: any) => {
      Worklet = processor;
    },
  });
  const processor = new Worklet();
  const left = new Float32Array(128).fill(0.5),
    right = new Float32Array(128).fill(-0.25);
  for (let i = 0; i < 57; i++)
    processor.process([[left, right]], [[new Float32Array(128)]]);
  processor.port.onmessage({ data: "stop" });
  expect(messages.map((m) => m.type)).toEqual(["audio", "audio", "flushed"]);
  expect(messages[0].samples?.length).toBe(7200);
  expect(messages[1].samples?.length).toBe(96);
  expect(messages[1].samples?.[0]).toBe(0.125);
  expect(processor.process([[left]], [[new Float32Array(128)]])).toBe(false);
});

import { latestSnapshot, type Session } from "./api";
it("discards an older snapshot arriving after a user correction or speaker update", () => {
  const current = { id: "session", snapshot_revision: 9 } as Session;
  expect(
    latestSnapshot(current, { id: "session", snapshot_revision: 8 } as Session),
  ).toBe(current);
  expect(
    latestSnapshot(current, { id: "session", snapshot_revision: 10 } as Session)
      .snapshot_revision,
  ).toBe(10);
});
