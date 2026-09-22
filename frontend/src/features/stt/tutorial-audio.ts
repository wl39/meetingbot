/** Encode a browser recording as a mono WAV that the file workflow can accept. */
export function recordingWav(chunks: Float32Array[], sampleRate: number): File {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const samples = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    samples.set(chunk, offset);
    offset += chunk.length;
  }
  // Speech needs no more than 16 kHz here; keeping a compact WAV also lets
  // recordings fit the same upload limit as other tutorial files.
  const outputRate = Math.min(16000, sampleRate);
  const frames = Math.floor((length * outputRate) / sampleRate);
  const buffer = new ArrayBuffer(44 + frames * 2);
  const view = new DataView(buffer);
  const text = (at: number, value: string) => {
    for (let index = 0; index < value.length; index++)
      view.setUint8(at + index, value.charCodeAt(index));
  };
  text(0, "RIFF");
  view.setUint32(4, buffer.byteLength - 8, true);
  text(8, "WAVE");
  text(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, outputRate, true);
  view.setUint32(28, outputRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, "data");
  view.setUint32(40, frames * 2, true);
  const ratio = sampleRate / outputRate;
  for (let index = 0; index < frames; index++) {
    const start = Math.floor(index * ratio);
    const end = Math.min(length, Math.floor((index + 1) * ratio));
    let sum = 0;
    for (let position = start; position < end; position++)
      sum += samples[position];
    const value = Math.max(-1, Math.min(1, sum / Math.max(1, end - start)));
    view.setInt16(
      44 + index * 2,
      Math.round(value * (value < 0 ? 32768 : 32767)),
      true,
    );
  }
  return new File([buffer], "내 첫 음성 테스트.wav", { type: "audio/wav" });
}
