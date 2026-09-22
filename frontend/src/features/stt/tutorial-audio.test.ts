import { describe, expect, it } from "vitest";
import { recordingWav } from "./tutorial-audio";

describe("tutorial recording upload", () => {
  it("writes a complete compact mono WAV across chunk boundaries", async () => {
    const file = recordingWav(
      [
        new Float32Array([1, 1, 1, -1]),
        new Float32Array([-1, -1, 0.5, 0.5, 0.5]),
      ],
      48000,
    );
    const bytes = await file.arrayBuffer();
    const view = new DataView(bytes);
    expect(file.type).toBe("audio/wav");
    expect(file.name).toMatch(/\.wav$/);
    expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe("RIFF");
    expect(new TextDecoder().decode(bytes.slice(8, 12))).toBe("WAVE");
    expect(view.getUint32(4, true)).toBe(bytes.byteLength - 8);
    expect(view.getUint16(22, true)).toBe(1);
    expect(view.getUint32(24, true)).toBe(16000);
    expect(view.getUint32(28, true)).toBe(32000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(view.getUint32(40, true)).toBe(6);
    expect(
      [0, 1, 2].map((index) => view.getInt16(44 + index * 2, true)),
    ).toEqual([32767, -32768, 16384]);
  });
  it("preserves low-rate input and clamps out-of-range microphone samples", async () => {
    const file = recordingWav([new Float32Array([1.1, -1.2, 0])], 8000);
    const view = new DataView(await file.arrayBuffer());
    expect(view.getUint32(24, true)).toBe(8000);
    expect(view.getInt16(44, true)).toBe(32767);
    expect(view.getInt16(46, true)).toBe(-32768);
    expect(view.getInt16(48, true)).toBe(0);
  });
});
