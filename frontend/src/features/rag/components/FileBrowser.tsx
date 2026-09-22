import { useState, type ReactNode } from "react";
import { ArrowUp, ChevronRight, Folder, List, FolderTree } from "lucide-react";
import { directoryEntries, sortFiles, type BrowserItem } from "./file-browser";

export default function FileBrowser<T extends BrowserItem>({
  items,
  renderFile,
  rootLabel = "전체 파일",
  selection,
  pinIssues = false,
}: {
  items: T[];
  renderFile: (item: T) => ReactNode;
  rootLabel?: string;
  selection?: {
    selected: ReadonlySet<string>;
    disabled: boolean;
    eligible: (item: T) => boolean;
    toggle: (paths: string[], checked: boolean) => void;
  };
  pinIssues?: boolean;
}) {
  const [mode, setMode] = useState<"directory" | "list">("directory");
  const [directory, setDirectory] = useState("");
  const [limit, setLimit] = useState(200);
  const current =
    directory && items.some((f) => f.path.startsWith(directory + "/"))
      ? directory
      : "";
  const entries = directoryEntries(items, current);
  const files = mode === "list" ? sortFiles(items) : entries.files;
  const issues = sortFiles(items.filter((f) => f.attention));
  const parts = current ? current.split("/") : [];
  function navigate(path: string) {
    setDirectory(path);
    setLimit(200);
  }
  return (
    <div className="rag-browser">
      {pinIssues && issues.length > 0 && (
        <section className="rag-browser-issues" aria-label="확인이 필요한 파일">
          <h3>확인 필요 · {issues.length}개 파일</h3>
          <p>문제가 있는 파일을 폴더 위치와 관계없이 먼저 표시합니다.</p>
          <div className="rag-browser-rows">
            {issues.map((item) => (
              <div key={item.path}>{renderFile(item)}</div>
            ))}
          </div>
        </section>
      )}
      <div className="rag-browser-toolbar">
        <span>{items.length}개 파일</span>
        <div role="group" aria-label="파일 보기 방식">
          <button
            type="button"
            aria-pressed={mode === "directory"}
            onClick={() => {
              setMode("directory");
              setLimit(200);
            }}
          >
            <FolderTree size={16} />
            디렉토리별로 보기
          </button>
          <button
            type="button"
            aria-pressed={mode === "list"}
            onClick={() => {
              setMode("list");
              setLimit(200);
            }}
          >
            <List size={16} />
            리스트로 보기
          </button>
        </div>
      </div>
      {mode === "directory" && (
        <nav className="rag-browser-breadcrumbs" aria-label="현재 폴더">
          <button
            type="button"
            aria-label="상위 폴더로 이동"
            disabled={!current}
            onClick={() => navigate(parts.slice(0, -1).join("/"))}
          >
            <ArrowUp size={16} />
          </button>
          <button type="button" onClick={() => navigate("")}>
            {rootLabel}
          </button>
          {parts.map((part, index) => (
            <span key={index}>
              <ChevronRight size={14} />
              <button
                type="button"
                aria-current={
                  index === parts.length - 1 ? "location" : undefined
                }
                onClick={() => navigate(parts.slice(0, index + 1).join("/"))}
              >
                {part}
              </button>
            </span>
          ))}
        </nav>
      )}
      <div className="rag-browser-rows">
        {mode === "directory" &&
          entries.folders.map((folder) => {
            const eligible = selection
              ? folder.files.filter(selection.eligible).map((f) => f.path)
              : [];
            const selected = eligible.filter((path) =>
              selection?.selected.has(path),
            ).length;
            const warnings = folder.files.filter((f) => f.attention).length;
            return (
              <div className="rag-browser-folder" key={folder.path}>
                {selection && (
                  <input
                    type="checkbox"
                    aria-label={`${folder.path} 폴더 전체 선택`}
                    disabled={selection.disabled || !eligible.length}
                    checked={
                      eligible.length > 0 && selected === eligible.length
                    }
                    ref={(el) => {
                      if (el)
                        el.indeterminate =
                          selected > 0 && selected < eligible.length;
                    }}
                    onChange={(e) =>
                      selection.toggle(eligible, e.target.checked)
                    }
                  />
                )}
                <button type="button" onClick={() => navigate(folder.path)}>
                  <Folder size={23} />
                  <span>
                    <strong>{folder.name}</strong>
                    <small>
                      {folder.files.length}개 파일
                      {selection ? ` · ${selected}개 선택` : ""}
                      {warnings ? ` · 확인 필요 ${warnings}개` : ""}
                    </small>
                  </span>
                  <ChevronRight size={18} />
                </button>
              </div>
            );
          })}
        {files.slice(0, limit).map((item) => (
          <div key={item.path}>{renderFile(item)}</div>
        ))}
        {!files.length && (mode === "list" || !entries.folders.length) && (
          <div className="rag-small-empty">파일이 없습니다.</div>
        )}
      </div>
      {files.length > limit && (
        <button
          className="rag-secondary rag-upload-more"
          type="button"
          onClick={() => setLimit((n) => n + 200)}
        >
          파일 더 보기 ({limit} / {files.length})
        </button>
      )}
    </div>
  );
}
