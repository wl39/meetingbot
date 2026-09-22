// Source reference for the standalone worklet in public/audio-worklet.js.
// The worklet has no imports and runs at the actual AudioContext sample rate.
export function packFrame(
  sequence: number,
  start: number,
  samples: Float32Array,
): ArrayBuffer {
  const buffer = new ArrayBuffer(16 + samples.length * 4);
  const view = new DataView(buffer);
  view.setUint32(0, sequence, true);
  view.setBigUint64(4, BigInt(start), true);
  view.setUint32(12, samples.length, true);
  samples.forEach((value, i) => view.setFloat32(16 + i * 4, value, true));
  return buffer;
}
