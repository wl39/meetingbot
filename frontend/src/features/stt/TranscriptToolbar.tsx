import { useState, type KeyboardEvent } from "react";
import { Download, FileText, List } from "lucide-react";
import type { Session, TranscriptMode } from "./api";
import { TranscriptDownloadDialog } from "./TranscriptDownloadDialog";
import "./transcript-controls.css";

export function TranscriptToolbar({
  session,
  mode,
  canConvert,
  onModeChange,
  id,
  description,
}: {
  session: Session | null;
  mode: TranscriptMode;
  canConvert: boolean;
  onModeChange: (mode: TranscriptMode) => void;
  id: string;
  description: string;
}) {
  const [exportOpen, setExportOpen] = useState(false);
  function navigateTabs(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const tabs = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>(
        '[role="tab"]:not(:disabled)',
      ),
    );
    const current = tabs.indexOf(document.activeElement as HTMLButtonElement);
    const index =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? tabs.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) %
            tabs.length;
    tabs[index]?.focus();
    tabs[index]?.click();
  }
  return (
    <>
      <div className="transcript-mode-bar">
        <div className="transcript-tab-row">
          <div
            className="transcript-tabs"
            role="tablist"
            aria-label="대본 보기 방식"
            onKeyDown={navigateTabs}
          >
            {(
              [
                { value: "script", label: "대본 보기", icon: FileText },
                { value: "utterance", label: "발화별 보기", icon: List },
              ] as const
            ).map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                type="button"
                role="tab"
                id={`${id}-${value}`}
                aria-selected={mode === value}
                aria-controls={`${id}-panel`}
                tabIndex={mode === value ? 0 : -1}
                disabled={value === "script" && !canConvert}
                title={
                  value === "script" && !canConvert
                    ? "정리가 끝나면 대본 보기로 읽을 수 있습니다."
                    : undefined
                }
                onClick={() => onModeChange(value)}
              >
                <Icon size={16} aria-hidden="true" />
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="transcript-download-badge"
            disabled={!session?.utterances.length}
            aria-haspopup="dialog"
            onClick={() => setExportOpen(true)}
          >
            <Download size={14} aria-hidden="true" />
            대본 다운로드
          </button>
        </div>
        <p className="transcript-mode-description">{description}</p>
      </div>
      {exportOpen && session && (
        <TranscriptDownloadDialog
          key={session.id}
          session={session}
          initialMode={mode}
          canConvert={canConvert}
          onClose={() => setExportOpen(false)}
        />
      )}
    </>
  );
}
