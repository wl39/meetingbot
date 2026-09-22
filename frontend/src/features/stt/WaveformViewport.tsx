import { useEffect, useRef, useState } from "react";
import { themeTokens, useThemeColor } from "../../workspace/theme";
import {
  ChevronLeft,
  ChevronRight,
  LocateFixed,
  Minus,
  Plus,
} from "lucide-react";
import {
  clamp,
  PEAKS_PER_SECOND,
  playerTime,
  rulerTime,
  TILE_SECONDS,
  visibleRange,
  type AudioSeek,
} from "./waveform";

type Tile = { start: number; peaks: Float32Array };
const ZOOMS = [4, 8, 12, 24, 48, 96];
const HEIGHT = 214;

export function WaveformViewport({
  file,
  duration,
  position,
  seek,
  onSeek,
}: {
  file: File;
  duration: number;
  position: number;
  seek: AudioSeek | null;
  onSeek: (seconds: number) => void;
}) {
  const themeColor = useThemeColor();
  const viewport = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const worker = useRef<Worker | null>(null);
  const drag = useRef<{ x: number; scroll: number; moved: boolean } | null>(
    null,
  );
  const [width, setWidth] = useState(300);
  const [seconds, setSeconds] = useState(12);
  const [center, setCenter] = useState(0);
  const [follow, setFollow] = useState(true);
  const [data, setData] = useState<{ key: string; tiles: Tile[] }>({
    key: "",
    tiles: [],
  });
  const [error, setError] = useState("");
  const scale = width / seconds;
  const range = visibleRange(center, seconds, duration);
  const first = Math.floor(range.start / TILE_SECONDS);
  const last = Math.max(first, Math.ceil(range.end / TILE_SECONDS) - 1);
  const requestKey = `${first}:${last}`;
  const loading = data.key !== requestKey && !error;
  const playbackRatio = duration > 0 ? clamp(position / duration, 0, 1) : 0;
  // Match the range thumb's travel: its center stays 8px inside either edge.
  const playbackOffset = `calc(${playbackRatio * 100}% + ${8 - playbackRatio * 16}px)`;

  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      // Layout transitions can briefly report a hidden, zero-width viewport.
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const next = new Worker(new URL("./waveform.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.current = next;
    next.onmessage = ({ data: message }) => {
      if (message.type === "peaks") {
        setData(message);
        setError("");
      } else if (message.type === "error") setError(message.message);
    };
    next.onerror = () =>
      setError(
        "파형을 불러오지 못했습니다. 파일을 다시 연결해 주세요. 음성 재생은 계속 이용할 수 있습니다.",
      );
    next.postMessage({ type: "open", file });
    return () => {
      next.terminate();
      worker.current = null;
    };
  }, [file]);

  useEffect(() => {
    if (duration > 0)
      worker.current?.postMessage({
        type: "range",
        start: first * TILE_SECONDS,
        end: Math.min(duration, (last + 1) * TILE_SECONDS),
        key: requestKey,
      });
  }, [file, duration, requestKey]);

  function scrollTo(value: number) {
    if (viewport.current) {
      viewport.current.scrollLeft = clamp(value, 0, duration) * scale;
      setCenter(viewport.current.scrollLeft / scale);
    }
  }

  useEffect(() => {
    if (follow) scrollTo(position);
  }, [position, follow, scale]);

  useEffect(() => {
    if (!seek) return;
    const length = (seek.endMs - seek.ms) / 1000;
    setSeconds((current) =>
      length > current * 0.45
        ? (ZOOMS.find((s) => s >= length * 2.25) ?? 96)
        : current,
    );
    setFollow(true);
    scrollTo(seek.ms / 1000);
  }, [seek]);

  // Keep the same point centered when zooming or resizing while browsing.
  const previousScale = useRef(scale);
  useEffect(() => {
    if (!follow && previousScale.current !== scale) scrollTo(center);
    previousScale.current = scale;
  }, [scale]);

  useEffect(() => {
    const el = viewport.current;
    if (!el) return;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey) return;
      event.preventDefault();
      setFollow(false);
      el.scrollLeft +=
        Math.abs(event.deltaX) > Math.abs(event.deltaY)
          ? event.deltaX
          : event.deltaY;
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, []);

  useEffect(() => {
    const el = canvas.current;
    if (!el || !width) return;
    const dpr = window.devicePixelRatio || 1;
    el.width = Math.round(width * dpr);
    el.height = HEIGHT * dpr;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const palette = themeTokens(themeColor);
    const hue = palette["--theme-hue"];
    const accent = palette["--theme-primary"];
    const xAt = (time: number) => width / 2 + (time - center) * scale;
    const top = 10,
      bottom = 174,
      middle = 92;
    ctx.fillStyle = `hsl(${hue} 20% 96%)`;
    ctx.fillRect(0, top, width, bottom - top);
    ctx.fillStyle = `hsl(${hue} 20% 98%)`;
    ctx.fillRect(0, top, clamp(xAt(0), 0, width), bottom - top);
    ctx.fillRect(clamp(xAt(duration), 0, width), top, width, bottom - top);
    if (seek) {
      const left = clamp(xAt(seek.ms / 1000), 0, width);
      const right = clamp(xAt(seek.endMs / 1000), 0, width);
      if (right > left) {
        ctx.fillStyle = `hsl(${hue} 45% 90%)`;
        ctx.fillRect(left, top, right - left, bottom - top);
        ctx.fillStyle = accent;
        for (const edge of [seek.ms / 1000, seek.endMs / 1000]) {
          const x = xAt(edge);
          if (x >= 0 && x <= width) ctx.fillRect(x, top, 1, bottom - top);
        }
      }
    }
    // Only visible bars are drawn. The canvas stays viewport-sized even at 300 minutes.
    const spacing = 3;
    const visibleStart = center - seconds / 2;
    const barStart = Math.floor((visibleStart * scale) / spacing);
    for (let bar = barStart; bar < barStart + width / spacing + 2; bar++) {
      const start = (bar * spacing) / scale;
      const end = start + spacing / scale;
      if (end <= 0 || start >= duration) continue;
      let peak = 0;
      let found = false;
      for (const tile of data.tiles) {
        const a = Math.max(
          0,
          Math.floor((start - tile.start) * PEAKS_PER_SECOND),
        );
        const b = Math.min(
          tile.peaks.length,
          Math.ceil((end - tile.start) * PEAKS_PER_SECOND),
        );
        if (b > a) found = true;
        for (let i = a; i < b; i++) peak = Math.max(peak, tile.peaks[i]);
      }
      if (!found) continue;
      const selected =
        seek && end > seek.ms / 1000 && start < seek.endMs / 1000;
      ctx.fillStyle = selected ? accent : `hsl(${hue} 10% 42%)`;
      const amplitude = Math.max(1, Math.sqrt(Math.min(1, peak)) * 65);
      ctx.fillRect(xAt(start), middle - amplitude, 1.5, amplitude * 2);
    }
    const tick = seconds <= 8 ? 1 : seconds <= 24 ? 2 : seconds <= 48 ? 5 : 10;
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "center";
    for (
      let t = Math.max(0, Math.ceil(visibleStart / (tick / 4)) * (tick / 4));
      t <= Math.min(duration, visibleStart + seconds);
      t += tick / 4
    ) {
      const major = Math.abs(t / tick - Math.round(t / tick)) < 0.001;
      const x = xAt(t);
      ctx.fillStyle = `hsl(${hue} 15% 85%)`;
      ctx.fillRect(x, bottom, 1, major ? 10 : 5);
      if (major && x > 16 && x < width - 16) {
        ctx.fillStyle = `hsl(${hue} 10% 48%)`;
        ctx.fillText(rulerTime(t), x, bottom + 26);
      }
    }
    const playX = xAt(position);
    if (playX >= 0 && playX <= width) {
      ctx.fillStyle = accent;
      ctx.fillRect(playX - 0.75, top, 1.5, bottom - top);
      for (const y of [top, bottom]) {
        ctx.beginPath();
        ctx.arc(playX, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, [width, center, seconds, duration, position, seek, data, themeColor]);

  function browse(value: number) {
    setFollow(false);
    scrollTo(value);
  }

  return (
    <div className="waveform-player">
      <div className="waveform-toolbar">
        <span>
          구간 확대 <b>{seconds}초</b>
        </span>
        <div>
          <button
            aria-label="파형 축소"
            disabled={seconds === 96}
            onClick={() =>
              setSeconds(
                ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(seconds) + 1)],
              )
            }
          >
            <Minus size={14} />
          </button>
          <button
            aria-label="파형 확대"
            disabled={seconds === 4}
            onClick={() =>
              setSeconds(ZOOMS[Math.max(0, ZOOMS.indexOf(seconds) - 1)])
            }
          >
            <Plus size={14} />
          </button>
        </div>
      </div>
      <div
        ref={viewport}
        className="waveform-scroll"
        role="region"
        aria-label="확대된 음성 파형. 좌우로 드래그하거나 스크롤하여 탐색"
        tabIndex={0}
        onScroll={() => setCenter((viewport.current?.scrollLeft ?? 0) / scale)}
        onPointerDown={() => setFollow(false)}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
            event.preventDefault();
            browse(
              center + ((event.key === "ArrowLeft" ? -1 : 1) * seconds) / 2,
            );
          }
          if (event.key === "Home" || event.key === "End") {
            event.preventDefault();
            browse(event.key === "Home" ? 0 : duration);
          }
        }}
      >
        <div
          className="waveform-track"
          style={{ width: Math.ceil(duration * scale + width) }}
        >
          <canvas
            ref={canvas}
            style={{ width, height: HEIGHT }}
            aria-label={
              seek
                ? `선택한 발화 ${rulerTime(seek.ms / 1000)}부터 ${rulerTime(seek.endMs / 1000)}까지 녹색 강조`
                : "음성 파형"
            }
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              drag.current = {
                x: event.clientX,
                scroll: viewport.current?.scrollLeft ?? 0,
                moved: false,
              };
              event.currentTarget.setPointerCapture(event.pointerId);
            }}
            onPointerMove={(event) => {
              if (!drag.current || !viewport.current) return;
              const delta = event.clientX - drag.current.x;
              if (Math.abs(delta) > 4) drag.current.moved = true;
              if (drag.current.moved)
                viewport.current.scrollLeft = drag.current.scroll - delta;
            }}
            onPointerUp={(event) => {
              if (!drag.current) return;
              if (!drag.current.moved) {
                const x =
                  event.clientX -
                  event.currentTarget.getBoundingClientRect().left;
                onSeek(clamp(center + (x - width / 2) / scale, 0, duration));
                setFollow(true);
              }
              drag.current = null;
            }}
            onPointerCancel={() => {
              drag.current = null;
            }}
          />
        </div>
      </div>
      {error ? (
        <p className="waveform-message player-error" role="status">
          {error}
        </p>
      ) : (
        <p className="waveform-message" role="status">
          {loading
            ? "이 구간의 파형을 읽고 있습니다…"
            : "좌우로 밀어 탐색 · 파형을 눌러 재생 위치 이동"}
        </p>
      )}
      <div className="waveform-navigation">
        <button
          aria-label="이전 파형 구간"
          disabled={center <= 0}
          onClick={() => browse(center - seconds / 2)}
        >
          <ChevronLeft size={16} />
        </button>
        <div
          className={`waveform-navigation-track ${follow ? "following" : ""}`}
        >
          <span
            className="waveform-navigation-time"
            style={{
              left: `clamp(44px, ${playbackOffset}, calc(100% - 44px))`,
            }}
          >
            재생 {playerTime(position).replace(/^0:/, "")}
          </span>
          <div className="waveform-navigation-rail" aria-hidden="true">
            <span style={{ width: `${playbackRatio * 100}%` }} />
          </div>
          <input
            aria-label="파형 탐색 위치"
            aria-valuetext={`화면 중심 ${playerTime(center)}, 현재 재생 ${playerTime(position)}`}
            type="range"
            min={0}
            max={duration || 1}
            step={0.1}
            value={center}
            onChange={(e) => browse(Number(e.target.value))}
          />
          <span
            className="waveform-position-marker"
            style={{ left: playbackOffset }}
            title={`현재 재생 위치 ${playerTime(position)}`}
            aria-hidden="true"
          />
        </div>
        <button
          aria-label="다음 파형 구간"
          disabled={center >= duration}
          onClick={() => browse(center + seconds / 2)}
        >
          <ChevronRight size={16} />
        </button>
      </div>
      <div className="waveform-view-label">
        <span>
          {rulerTime(range.start)} – {rulerTime(range.end)}
        </span>
        <button
          className={follow ? "following" : ""}
          onClick={() => {
            setFollow(true);
            scrollTo(position);
          }}
        >
          <LocateFixed size={12} />
          재생 위치로
        </button>
      </div>
    </div>
  );
}
