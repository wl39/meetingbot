import { useEffect, useRef, useState } from "react";
import {
  Headphones,
  FileAudio,
  RotateCcw,
  RotateCw,
  Play,
  Pause,
} from "lucide-react";
import { time, type Session } from "./api";
import { WaveformViewport } from "./WaveformViewport";
import { clamp, playerTime, type AudioSeek } from "./waveform";

export function LocalAudioPlayer({
  file,
  session,
  onFile,
  seek,
  onPosition,
  syncEnabled,
  onSyncChange,
  highlightWords,
  onHighlightWordsChange,
}: {
  file: File | null;
  session: Session | null;
  onFile: (file: File) => void;
  seek: AudioSeek | null;
  onPosition: (ms: number) => void;
  syncEnabled: boolean;
  onSyncChange: (enabled: boolean) => void;
  highlightWords: boolean;
  onHighlightWordsChange: (enabled: boolean) => void;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [url, setUrl] = useState<string>();
  const [duration, setDuration] = useState(0);
  const [position, setPosition] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [error, setError] = useState("");
  const [selection, setSelection] = useState<AudioSeek | null>(null);
  const pendingSeek = useRef<AudioSeek | null>(null);
  const initialSeek = useRef(seek);

  useEffect(() => {
    setDuration(0);
    setPosition(0);
    setPlaying(false);
    setError("");
    setSelection(null);
    pendingSeek.current = null;
    onPosition(0);
    if (!file) {
      setUrl(undefined);
      return;
    }
    const next = URL.createObjectURL(file);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [file]);

  function updatePosition(value: number) {
    setPosition(value);
    onPosition(value * 1000);
  }
  function moveTo(value: number) {
    if (!audio.current || !Number.isFinite(audio.current.duration)) return;
    const target = clamp(value, 0, audio.current.duration);
    audio.current.currentTime = target;
    updatePosition(target);
  }
  function play() {
    if (!audio.current) return;
    const element = audio.current;
    setError("");
    void element.play().catch((reason: unknown) => {
      // Pausing or replacing a source can legitimately abort a pending play().
      if (reason instanceof DOMException && reason.name === "AbortError")
        return;
      if (audio.current === element)
        setError("재생 버튼을 눌러 음성을 시작해 주세요.");
    });
  }
  useEffect(() => {
    if (!seek || !file || seek === initialSeek.current) return;
    setSelection(seek);
    if (!audio.current || audio.current.readyState < 1) {
      pendingSeek.current = seek;
      return;
    }
    moveTo(seek.ms / 1000);
    play();
  }, [seek]);

  useEffect(() => {
    if (!playing) return;
    let frame: number;
    let lastPositionUpdate = -Infinity;
    const tick = (now: number) => {
      const value = audio.current?.currentTime ?? 0;
      setPosition(value);
      // timeupdate can skip short words. Follow the media clock at 25 Hz
      // when highlighting, including after playback-rate changes.
      if (syncEnabled && highlightWords && now - lastPositionUpdate >= 40) {
        onPosition(value * 1000);
        lastPositionUpdate = now;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, syncEnabled, highlightWords, onPosition]);

  const selectedUtterance = session?.utterances.find(
    (u) => u.utterance_id === selection?.utteranceId,
  );
  const speaker = selectedUtterance
    ? session?.speakers[selectedUtterance.speaker_id || ""]
    : null;

  return (
    <aside className={`panel local-player ${file ? "" : "is-empty"}`}>
      <div className="panel-heading">
        <div>
          <h2>
            <Headphones size={19} /> 원본 듣기
          </h2>
          <p>대본과 함께 원본 음성을 확인하세요.</p>
        </div>
      </div>
      <div className="local-player-body">
        <div className="local-file-info">
          <FileAudio size={20} />
          <strong className="local-filename">
            {file?.name || session?.source_file?.name || "원본 음성 파일"}
          </strong>
        </div>
        <audio
          ref={audio}
          preload="metadata"
          src={url}
          onLoadedMetadata={() => {
            const el = audio.current!;
            setDuration(Number.isFinite(el.duration) ? el.duration : 0);
            el.playbackRate = rate;
            if (pendingSeek.current) {
              moveTo(pendingSeek.current.ms / 1000);
              pendingSeek.current = null;
              play();
            }
          }}
          onTimeUpdate={() => updatePosition(audio.current?.currentTime ?? 0)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onError={() => {
            if (file && url)
              setError(
                "이 브라우저에서 재생할 수 없는 파일입니다. 원본의 형식과 재생 상태를 확인해 주세요.",
              );
          }}
        />
        {file && duration > 0 ? (
          <WaveformViewport
            key={url}
            file={file}
            duration={duration}
            position={position}
            seek={selection}
            onSeek={moveTo}
          />
        ) : (
          <div className="waveform-empty">
            <Headphones size={30} />
            <p>
              {file
                ? error
                  ? "이 파일을 재생할 수 없습니다.\n아래 안내를 확인해 주세요."
                  : "음성 파일을 준비하고 있습니다…"
                : "원본 파일을 연결하면\n확대된 음성 파형이 표시됩니다."}
            </p>
          </div>
        )}
        <div
          className={`selected-utterance ${selection ? "has-selection" : ""}`}
        >
          {selection ? (
            <>
              <span className="selection-dot" />
              <b>{speaker || "선택한 발화"}</b>
              <span>
                {time(selection.ms)} – {time(selection.endMs)}
              </span>
            </>
          ) : (
            <span>대본의 ▶ 버튼을 누르면 발화 구간을 강조합니다.</span>
          )}
        </div>
        <div className="player-clock" aria-label="현재 재생 시간">
          {playerTime(position)}
          <span>전체 {playerTime(duration).slice(0, -3)}</span>
        </div>
        <div className="player-transport">
          <button
            disabled={!duration}
            onClick={() => moveTo((audio.current?.currentTime ?? 0) - 10)}
            aria-label="10초 뒤로"
          >
            <RotateCcw size={21} />
            <span>10</span>
          </button>
          <button
            className="player-toggle"
            disabled={!duration}
            aria-label={playing ? "일시 정지" : "음성 재생"}
            onClick={() => {
              if (playing) audio.current?.pause();
              else play();
            }}
          >
            {playing ? (
              <Pause size={23} fill="currentColor" />
            ) : (
              <Play size={23} fill="currentColor" />
            )}
          </button>
          <button
            disabled={!duration}
            onClick={() => moveTo((audio.current?.currentTime ?? 0) + 10)}
            aria-label="10초 앞으로"
          >
            <RotateCw size={21} />
            <span>10</span>
          </button>
        </div>
        <div className="player-bottom">
          <label>
            재생 속도
            <select
              aria-label="재생 속도"
              value={rate}
              onChange={(e) => {
                const value = Number(e.target.value);
                setRate(value);
                if (audio.current) audio.current.playbackRate = value;
              }}
            >
              {[0.75, 1, 1.25, 1.5, 2].map((speed) => (
                <option key={speed} value={speed}>
                  {speed}×
                </option>
              ))}
            </select>
          </label>
          <button
            className="local-attach"
            onClick={() => input.current?.click()}
          >
            {file ? "파일 다시 연결" : "원본 파일 연결"}
          </button>
        </div>
        <fieldset className="player-sync">
          <legend>대본 싱크</legend>
          <label>
            <input
              type="radio"
              name="transcript-sync"
              checked={syncEnabled}
              onChange={() => onSyncChange(true)}
            />
            싱크 켜기
          </label>
          <label>
            <input
              type="radio"
              name="transcript-sync"
              checked={!syncEnabled}
              onChange={() => onSyncChange(false)}
            />
            싱크 끄기
          </label>
          <p>켜면 재생 시간에 맞춰 대본이 자동으로 이동합니다.</p>
          <label className="word-highlight-option">
            <input
              type="checkbox"
              checked={highlightWords}
              disabled={!syncEnabled}
              onChange={(e) => onHighlightWordsChange(e.target.checked)}
              aria-describedby="word-highlight-help"
            />
            현재 단어 강조
          </label>
          <p id="word-highlight-help">
            {syncEnabled
              ? "재생 중인 단어를 강조합니다. 단어를 누르면 그 위치부터 재생합니다. 수정한 대본은 재생 위치와 조금 다를 수 있습니다."
              : "싱크를 켜면 현재 단어 강조를 선택할 수 있습니다."}
          </p>
        </fieldset>
        {error && (
          <p role="alert" className="player-error">
            {error}
          </p>
        )}
        <input
          ref={input}
          type="file"
          accept=".wav,.mp3,.m4a,.flac"
          className="visually-hidden"
          onChange={(e) => {
            const selected = e.target.files?.[0];
            if (selected) onFile(selected);
            e.target.value = "";
          }}
        />
        <small>
          원본은 내 기기에서 재생됩니다. 새로고침 후에는 같은 파일을 다시 연결해
          주세요.
        </small>
      </div>
    </aside>
  );
}
