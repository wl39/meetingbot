export type AudioSeek = {
  ms: number;
  endMs: number;
  utteranceId: string;
  key: number;
};
export const PEAKS_PER_SECOND = 100;
export const TILE_SECONDS = 10;

export function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value));
}

// Interleaved channels are combined by magnitude, so opposite-phase stereo
// does not disappear from the waveform. Clip samples to the requested tile.
export function addPeaks(
  peaks: Float32Array,
  pcm: Float32Array,
  channels: number,
  sampleRate: number,
  timestamp: number,
  start: number,
) {
  for (let frame = 0; frame < pcm.length / channels; frame++) {
    const bin = Math.floor(
      (timestamp + frame / sampleRate - start) * PEAKS_PER_SECOND + 1e-7,
    );
    if (bin < 0 || bin >= peaks.length) continue;
    for (let c = 0; c < channels; c++) {
      peaks[bin] = Math.max(peaks[bin], Math.abs(pcm[frame * channels + c]));
    }
  }
}

export function visibleRange(
  center: number,
  seconds: number,
  duration: number,
) {
  return {
    start: Math.max(0, center - seconds / 2),
    end: Math.min(duration, center + seconds / 2),
  };
}

export function rulerTime(seconds: number) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function playerTime(seconds: number) {
  const cs = Math.max(0, Math.floor(seconds * 100));
  return `${Math.floor(cs / 360000)}:${String(Math.floor(cs / 6000) % 60).padStart(2, "0")}:${String(Math.floor(cs / 100) % 60).padStart(2, "0")}.${String(cs % 100).padStart(2, "0")}`;
}
