import { describe, it, expect } from "vitest";
import { File } from "node:buffer";
import { uploadOrder } from "./file-upload";

function atom(type: string, size: number) {
  const data = new Uint8Array(size);
  new DataView(data.buffer).setUint32(0, size);
  [...type].forEach((c, i) => (data[4 + i] = c.charCodeAt(0)));
  return data;
}

describe("stream upload ordering", () => {
  it("sends all trailing M4A metadata blocks before middle audio blocks", async () => {
    const file = new File(
      [atom("ftyp", 16), atom("mdat", 144), atom("moov", 80)],
      "meeting.m4a",
    );
    const order = await uploadOrder(file as unknown as globalThis.File, 32);
    expect(order.slice(0, 4)).toEqual([0, 7, 5, 6]);
    expect([...order].sort((a, b) => a - b)).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
  });
  it("does not duplicate the only chunk of a small file", async () => {
    const file = new File([new Uint8Array(10)], "short.wav");
    expect(await uploadOrder(file as unknown as globalThis.File, 1024)).toEqual(
      [0],
    );
  });
  it("handles malformed atoms without skipping audio data", async () => {
    const file = new File([atom("mdat", 16), new Uint8Array(50)], "broken.m4a");
    expect(
      (await uploadOrder(file as unknown as globalThis.File, 16)).sort(),
    ).toEqual([0, 1, 2, 3, 4]);
  });
});
