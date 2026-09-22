import { FileText } from "lucide-react";
import { labels, reasons, type SourceFile } from "../api";
import FilePath from "./FilePath";
import FileBrowser from "./FileBrowser";
export function Badge({ state }: { state: string }) {
  return (
    <span
      className={
        "rag-badge " +
        (["READY", "PROCESSED", "AVAILABLE"].includes(state)
          ? "good"
          : [
                "FAILED",
                "PARTIAL",
                "CANCELLED",
                "REVIEWED",
                "PROCESSED_WITH_WARNINGS",
              ].includes(state)
            ? "warn"
            : "")
      }
    >
      <i />
      {labels[state] || "확인 필요"}
    </span>
  );
}
export function Files({
  files = [],
  onOpen,
  pinIssues = false,
}: {
  files?: SourceFile[];
  pinIssues?: boolean;
  onOpen?: (path: string) => void;
}) {
  return (
    <FileBrowser
      items={files.map((f) => ({
        ...f,
        path: f.relative_path,
        attention: ["FAILED", "REVIEWED", "PROCESSED_WITH_WARNINGS"].includes(
          f.state,
        ),
      }))}
      pinIssues={pinIssues}
      renderFile={(f) => (
        <div className="rag-file">
          <FileText size={17} />
          <span title={f.relative_path}>
            {onOpen && f.state !== "EXCLUDED" ? (
              <button
                className="rag-file-open"
                onClick={() => onOpen(f.relative_path)}
                aria-label={`${f.relative_path} 문서 열기`}
              >
                <FilePath path={f.relative_path} />
              </button>
            ) : (
              <FilePath path={f.relative_path} />
            )}
            <small>
              {f.reason
                ? reasons[f.reason] || "파일을 확인해 주세요"
                : f.bytes !== undefined
                  ? `${(f.bytes / 1024).toFixed(1)} KB`
                  : ""}
              {f.warnings?.length
                ? ` · ${f.warnings.map((w) => w.sheet).join(", ")}`
                : ""}
            </small>
          </span>
          <Badge state={f.state} />
          {onOpen && f.state !== "EXCLUDED" && (
            <button
              className="rag-secondary"
              onClick={() => onOpen(f.relative_path)}
            >
              문서 보기
            </button>
          )}
        </div>
      )}
    />
  );
}
