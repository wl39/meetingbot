import { useEffect, useId, useRef, useState } from "react";
import { Check, Download, FileText, List, LoaderCircle, X } from "lucide-react";
import {
  api,
  download,
  type ExportFormat,
  type ExportPreview,
  type Session,
  type TranscriptMode,
} from "./api";

const formats = [
  { value: "txt", label: "TXT", description: "텍스트 문서" },
  { value: "srt", label: "SRT", description: "시간이 담긴 자막" },
  { value: "json", label: "JSON", description: "구조화된 데이터" },
] as const;

export function TranscriptDownloadDialog({
  session,
  initialMode,
  canConvert,
  onClose,
}: {
  session: Session;
  initialMode: TranscriptMode;
  canConvert: boolean;
  onClose: () => void;
}) {
  const id = useId();
  const dialog = useRef<HTMLDialogElement>(null);
  const mounted = useRef(false);
  const [mode, setMode] = useState(initialMode);
  const [format, setFormat] = useState<ExportFormat>("txt");
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const view = canConvert ? mode : "utterance";

  useEffect(() => {
    mounted.current = true;
    const element = dialog.current!;
    const trigger = document.activeElement as HTMLElement | null;
    element.showModal();
    return () => {
      mounted.current = false;
      element.close();
      trigger?.focus();
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setPreview(null);
    setPreviewError("");
    api<ExportPreview>(
      `/sessions/${session.id}/export/preview?format=${format}&view=${view}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setPreview(result);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setPreviewError(
            "미리보기를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
          );
      });
    return () => controller.abort();
  }, [session.id, session.snapshot_revision, format, view]);

  async function save() {
    if (downloading) return;
    setDownloading(true);
    setDownloadError("");
    try {
      await download(session.id, format, view);
      if (mounted.current) onClose();
    } catch {
      if (mounted.current)
        setDownloadError(
          "대본을 다운로드하지 못했습니다. 연결을 확인하고 다시 시도해 주세요.",
        );
    } finally {
      if (mounted.current) setDownloading(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="transcript-export-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const bounds = event.currentTarget.getBoundingClientRect();
        if (
          event.clientX < bounds.left ||
          event.clientX > bounds.right ||
          event.clientY < bounds.top ||
          event.clientY > bounds.bottom
        )
          onClose();
      }}
    >
      <header className="export-dialog-heading">
        <span className="export-dialog-icon">
          <Download size={21} aria-hidden="true" />
        </span>
        <div>
          <h2 id={`${id}-title`}>대본 다운로드</h2>
          <p id={`${id}-description`}>읽기 방식과 파일 형식을 선택하세요.</p>
        </div>
        <button
          type="button"
          className="icon-button"
          aria-label="닫기"
          onClick={onClose}
          autoFocus
        >
          <X size={20} />
        </button>
      </header>
      <div className="export-dialog-body">
        <fieldset className="export-fieldset" disabled={downloading}>
          <legend>다운로드 방식</legend>
          <div className="export-mode-options">
            {(
              [
                {
                  value: "script",
                  label: "대화별 대본",
                  detail: "같은 화자의 연속 발화를 묶어서",
                  icon: FileText,
                },
                {
                  value: "utterance",
                  label: "발화별 대본",
                  detail: "발화마다 시간과 화자를 나누어서",
                  icon: List,
                },
              ] as const
            ).map(({ value, label, detail, icon: Icon }) => (
              <label
                key={value}
                className={`export-mode-option ${view === value ? "selected" : ""} ${value === "script" && !canConvert ? "unavailable" : ""}`}
              >
                <input
                  type="radio"
                  name={`${id}-mode`}
                  value={value}
                  checked={view === value}
                  disabled={value === "script" && !canConvert}
                  onChange={() => {
                    setMode(value);
                    setDownloadError("");
                  }}
                  aria-label={label}
                />
                <span className="export-option-heading">
                  <Icon size={18} aria-hidden="true" />
                  <b>{label}</b>
                  <span className="export-option-check">
                    <Check size={12} />
                  </span>
                </span>
                <span className="export-option-description">{detail}</span>
              </label>
            ))}
          </div>
          {!canConvert && (
            <p className="export-help">
              정리가 끝나면 대화별 대본도 다운로드할 수 있습니다.
            </p>
          )}
        </fieldset>
        <fieldset className="export-fieldset" disabled={downloading}>
          <legend>파일 형식</legend>
          <div className="export-format-options">
            {formats.map(({ value, label, description }) => (
              <label
                className={`export-format-option ${format === value ? "selected" : ""}`}
                key={value}
              >
                <input
                  type="radio"
                  name={`${id}-format`}
                  value={value}
                  checked={format === value}
                  aria-label={label}
                  onChange={() => {
                    setFormat(value);
                    setDownloadError("");
                  }}
                />
                <b>{label}</b>
                <span>{description}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <section
          className="export-preview"
          aria-label="다운로드 미리보기"
          aria-busy={!preview && !previewError}
        >
          <div className="export-preview-heading">
            <h3>미리보기</h3>
            <span>
              {view === "script" ? "대화별" : "발화별"} · {format.toUpperCase()}
            </span>
          </div>
          {previewError ? (
            <p role="alert" className="export-preview-status">
              {previewError}
            </p>
          ) : preview ? (
            <pre className="export-preview-content">
              {preview.content || "내보낼 대본이 없습니다."}
            </pre>
          ) : (
            <p className="export-preview-status" role="status">
              <LoaderCircle size={16} className="export-spinner" />
              미리보기를 불러오는 중…
            </p>
          )}
          <p className="export-preview-note">
            {preview
              ? `전체 ${preview.total_items}개 ${view === "script" ? "대화" : "발화"} 중 앞 ${preview.preview_items}개를 짧게 보여드려요. 파일에는 전체 내용이 저장됩니다.`
              : "선택한 방식과 파일 형식으로 대본 일부를 보여드려요."}
          </p>
        </section>
        {downloadError && (
          <p role="alert" className="export-error">
            {downloadError}
          </p>
        )}
      </div>
      <footer className="export-dialog-footer">
        <button type="button" onClick={onClose}>
          취소
        </button>
        <button
          type="button"
          className="primary"
          onClick={save}
          disabled={
            downloading ||
            (!preview && !previewError) ||
            preview?.total_items === 0
          }
        >
          {downloading ? (
            <LoaderCircle size={16} className="export-spinner" />
          ) : (
            <Download size={16} />
          )}
          {downloading
            ? "다운로드 준비 중…"
            : `${format.toUpperCase()} 다운로드`}
        </button>
      </footer>
    </dialog>
  );
}
