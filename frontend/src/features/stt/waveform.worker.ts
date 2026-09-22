import { Input, BlobSource, ALL_FORMATS, AudioSampleSink } from "mediabunny";
import { addPeaks, PEAKS_PER_SECOND, TILE_SECONDS } from "./waveform";

let input: Input;
let ready: Promise<AudioSampleSink>;
let serial = 0;
let busy = false;
let wanted: { start: number; end: number; key: string } | null = null;
const cache = new Map<number, Float32Array>();

async function render() {
  if (busy || !wanted || !ready) return;
  busy = true;
  try {
    const sink = await ready;
    while (wanted) {
      const request = wanted;
      const version = serial;
      const first = Math.floor(request.start / TILE_SECONDS);
      const last = Math.max(first, Math.ceil(request.end / TILE_SECONDS) - 1);
      const tiles: { start: number; peaks: Float32Array }[] = [];
      for (let tile = first; tile <= last; tile++) {
        let peaks = cache.get(tile);
        if (!peaks) {
          peaks = new Float32Array(TILE_SECONDS * PEAKS_PER_SECOND);
          for await (const sample of sink.samples(
            tile * TILE_SECONDS,
            (tile + 1) * TILE_SECONDS,
          )) {
            try {
              if (version !== serial) break;
              const pcm = new Float32Array(
                sample.numberOfFrames * sample.numberOfChannels,
              );
              sample.copyTo(pcm, { format: "f32", planeIndex: 0 });
              addPeaks(
                peaks,
                pcm,
                sample.numberOfChannels,
                sample.sampleRate,
                sample.timestamp,
                tile * TILE_SECONDS,
              );
            } finally {
              sample.close();
            }
          }
          if (version !== serial) break;
        }
        // Bounded LRU: at most 320 seconds of compact peaks, never full-file PCM.
        cache.delete(tile);
        cache.set(tile, peaks);
        if (cache.size > 32) cache.delete(cache.keys().next().value!);
        tiles.push({ start: tile * TILE_SECONDS, peaks });
      }
      if (version !== serial) continue;
      self.postMessage({ type: "peaks", key: request.key, tiles });
      wanted = null;
    }
  } catch {
    wanted = null;
    self.postMessage({
      type: "error",
      message:
        "이 브라우저에서 이 파일의 파형을 읽을 수 없습니다. Chrome 최신 버전이나 WAV·AAC 형식의 원본을 사용해 주세요. 음성 재생은 계속 이용할 수 있습니다.",
    });
  } finally {
    busy = false;
  }
}

self.onmessage = (event: MessageEvent) => {
  if (event.data.type === "open") {
    input = new Input({
      source: new BlobSource(event.data.file, {
        maxCacheSize: 4 * 1024 * 1024,
      }),
      formats: ALL_FORMATS,
    });
    ready = (async () => {
      const track = await input.getPrimaryAudioTrack();
      if (!track || !(await track.canDecode()))
        throw new Error("Unsupported audio codec");
      return new AudioSampleSink(track);
    })();
    // Attach a handler even if metadata has not triggered a range request yet.
    void ready.catch(() => {
      self.postMessage({
        type: "error",
        message:
          "이 파일의 파형을 읽을 수 없습니다. Chrome 최신 버전이나 WAV·AAC 형식의 원본을 사용해 주세요. 음성 재생은 계속 이용할 수 있습니다.",
      });
    });
  } else if (event.data.type === "range") {
    if (
      !Number.isFinite(event.data.start) ||
      !Number.isFinite(event.data.end) ||
      event.data.start < 0 ||
      event.data.end <= event.data.start
    )
      return;
    wanted = event.data;
    serial++;
    void render();
  }
};
