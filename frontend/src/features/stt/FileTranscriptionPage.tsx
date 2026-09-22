import { useState, useRef, useEffect } from "react";
import {
  Upload,
  FileAudio,
  ArrowRight,
  LoaderCircle,
  ChevronDown,
} from "lucide-react";
import {
  api,
  modelReady,
  terminal,
  states,
  type Health,
  type Session,
} from "./api";
import { Controls } from "./Controls";
import { useTranscriptionOptions } from "./useTranscriptionOptions";
import { uploadFileChunks } from "./file-upload";
import { DiarizationProgress } from "./DiarizationProgress";
import { useOnboarding } from "../onboarding/context";
export function FileTranscriptionPage({
  health,
  session,
  onSession,
  onError,
  onClear,
  file,
  onFile,
  onAssociate,
  onUploading,
}: {
  health: Health | null;
  session: Session | null;
  onSession: (s: Session) => void;
  onError: (s: string) => void;
  onClear: () => void;
  file: File | null;
  onFile: (file: File) => void;
  onAssociate: (sid: string, file: File) => void;
  onUploading: (active: boolean) => void;
}) {
  const [uploading, setUploading] = useState(false),
    [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState(0);
  const [showUpload, setShowUpload] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const uploadSid = useRef<string | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const input = useRef<HTMLInputElement>(null);
  const tutorial = useOnboarding();
  const busy =
    uploading ||
    !!(session && !terminal(session.state) && session.state !== "CREATED");
  const [options, setOptions] = useTranscriptionOptions(health, busy);
  const compact = !!session && !busy && !showUpload;
  useEffect(() => setShowUpload(false), [session?.id]);
  function choose(file?: File) {
    if (!file) return;
    const limitMB = health?.limits.file_mb ?? 4096;
    if (file.size > limitMB * 1024 * 1024) {
      onError(`파일은 ${limitMB}MB 이하여야 합니다.`);
      return;
    }
    if (!/\.(wav|mp3|m4a|flac)$/i.test(file.name)) {
      onError("WAV, MP3, M4A, FLAC 파일을 선택하세요.");
      return;
    }
    onError("");
    onFile(file);
    onClear();
  }
  async function start() {
    if (!file) return;
    const abort = new AbortController();
    controller.current = abort;
    uploadSid.current = null;
    setProgress(0);
    onError("");
    onUploading(true);
    setUploading(true);
    try {
      const result = await api<{ session_id: string; chunk_bytes: number }>(
        "/files/stream",
        {
          method: "POST",
          body: JSON.stringify({
            filename: file.name,
            size: file.size,
            options,
          }),
          signal: abort.signal,
        },
      );
      uploadSid.current = result.session_id;
      onAssociate(result.session_id, file);
      onSession(await api<Session>(`/sessions/${result.session_id}`));
      await uploadFileChunks(
        file,
        result.session_id,
        result.chunk_bytes,
        abort.signal,
        setProgress,
      );
    } catch (e) {
      if (!abort.signal.aborted) {
        // Prefer the decoder's specific failure (e.g. duration) over a later
        // chunk request's UPLOAD_NOT_FOUND response.
        let failed: Session | undefined;
        if (uploadSid.current)
          failed = await api<Session>(`/sessions/${uploadSid.current}`).catch(
            () => undefined,
          );
        if (failed?.state === "FAILED") onSession(failed);
        else onError(String(e));
      }
    } finally {
      setUploading(false);
      controller.current = null;
      onUploading(false);
    }
  }
  return (
    <section className={`panel input-panel ${compact ? "is-compact" : ""}`}>
      <div className="panel-heading">
        <div>
          <h2>
            <Upload size={19} />
            {compact ? "회의 음성" : "음성 파일"}
          </h2>
          <p>
            {compact
              ? session?.source_file?.name ||
                "아래 대본에서 회의 내용을 확인하세요."
              : "녹음 파일을 업로드해 대본으로 변환하세요."}
          </p>
        </div>
        <div className="source-actions">
          {session && !busy && (
            <button
              aria-expanded={!compact}
              onClick={() => setShowUpload((value) => !value)}
            >
              {compact ? "다른 파일 올리기" : "접기"}
              <ChevronDown size={16} />
            </button>
          )}
          {!compact && (
            <span className="subtle-badge">
              최대 {(health?.limits.file_seconds ?? 18000) / 60}분
            </span>
          )}
        </div>
      </div>
      <div hidden={compact}>
        {tutorial?.active && tutorial.audioFile && (
          <div className="action-row">
            <span>방금 녹음한 음성으로 이어서 해보세요.</span>
            <button
              disabled={busy}
              onClick={() => choose(tutorial.audioFile ?? undefined)}
            >
              <FileAudio size={16} /> 방금 녹음한 음성 사용
            </button>
          </div>
        )}
        <button
          disabled={busy}
          className={`dropzone ${drag ? "drag" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            if (!busy) choose(e.dataTransfer.files[0]);
          }}
          onClick={() => input.current?.click()}
        >
          <span className="upload-icon">
            {file ? <FileAudio size={27} /> : <Upload size={27} />}
          </span>
          <strong>{file ? file.name : "음성 파일 선택"}</strong>
          <span>
            {file
              ? `${(file.size / 1024 / 1024).toFixed(1)} MB · 눌러서 파일 변경`
              : "눌러서 선택하거나 파일을 여기에 놓으세요"}
          </span>
          <small>
            WAV · MP3 · M4A · FLAC &nbsp; / &nbsp; 최대{" "}
            {health?.limits.file_mb ?? 4096}MB
          </small>
        </button>
        <input
          ref={input}
          className="visually-hidden"
          type="file"
          accept=".wav,.mp3,.m4a,.flac"
          onChange={(e) => choose(e.target.files?.[0])}
        />
        <Controls
          value={options}
          onChange={setOptions}
          disabled={busy}
          health={health}
        />
        <div className="action-row">
          <span>파일을 선택하고 전사를 시작하세요.</span>
          <button
            className="primary"
            disabled={
              !file ||
              busy ||
              !modelReady(health, options.model) ||
              !!health?.active_session
            }
            onClick={start}
          >
            {busy ? (
              <LoaderCircle size={17} className="spin" />
            ) : (
              <ArrowRight size={17} />
            )}
            업로드 및 전사 시작
          </button>
          {session && !terminal(session.state) && (
            <button
              onClick={async () => {
                try {
                  controller.current?.abort();
                  await api(`/sessions/${session.id}`, { method: "DELETE" });
                  onClear();
                } catch (e) {
                  onError(String(e));
                }
              }}
            >
              취소
            </button>
          )}
        </div>
      </div>
      {uploading && (
        <div className="upload-progress">
          <progress value={progress} max={100} />
          <span>파일을 올리고 있습니다 · {progress}%</span>
        </div>
      )}
      {session && (
        <div className="progress">
          <span
            className={
              terminal(session.state) ? "status-dot" : "status-dot pulse"
            }
          />
          {states[session.state]}
          <small>
            {session.state === "TRANSCRIBING" &&
            session.metrics.progress_percent != null
              ? `${session.metrics.progress_percent}%`
              : terminal(session.state)
                ? ""
                : "잠시만 기다려 주세요"}
          </small>
        </div>
      )}
      {session?.state === "DIARIZING" && <DiarizationProgress />}
    </section>
  );
}
