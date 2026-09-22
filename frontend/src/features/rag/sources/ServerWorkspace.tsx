import {
  ArrowLeft,
  Check,
  ChevronRight,
  Database,
  FileText,
  Folder,
  FolderOpen,
  HardDrive,
  Loader2,
  Search,
} from "lucide-react";
import { reasons, type Workspace } from "../api";
import { Badge, Files } from "../components/SourceFiles";
import { useServerWorkspace } from "./useServerWorkspace";
export default function ServerWorkspace({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: (w: Workspace) => void;
  onError: (s: string) => void;
}) {
  const {
    roots,
    root,
    path,
    entries,
    cursor,
    filter,
    name,
    preview,
    chosen,
    loading,
    setRoot,
    setPath,
    setFilter,
    setName,
    choose,
    create,
    loadMore,
  } = useServerWorkspace({ onCreated, onError });
  return (
    <>
      <button className="rag-back" onClick={onClose}>
        <ArrowLeft size={16} />
        라이브러리로 돌아가기
      </button>
      <div className="rag-title-row">
        <div>
          <h1>공유 문서 연결</h1>
          <p>팀에서 사용하는 공유 폴더를 선택해 문서를 등록하세요.</p>
        </div>
      </div>
      <div className="rag-create-grid">
        <section className="rag-panel">
          <div className="rag-panel-heading">
            <h2>
              <FolderOpen size={19} />
              공유 폴더 탐색
            </h2>
            <span>읽기 전용</span>
          </div>
          <div className="rag-root-tabs">
            {roots.map((r) => (
              <button
                key={r.id}
                className={r.id === root ? "active" : ""}
                onClick={() => {
                  setRoot(r.id);
                  setPath("");
                }}
              >
                <HardDrive size={16} />
                {r.label}
              </button>
            ))}
          </div>
          {!roots.length && (
            <div className="rag-small-empty">
              연결된 공유 폴더가 없습니다. 관리자에게 문의해 주세요.
            </div>
          )}
          <div className="rag-breadcrumb">
            <button onClick={() => setPath("")}>전체 폴더</button>
            {path
              .split("/")
              .filter(Boolean)
              .map((p, i) => (
                <span key={i}>
                  <ChevronRight size={13} />
                  <button
                    onClick={() =>
                      setPath(
                        path
                          .split("/")
                          .slice(0, i + 1)
                          .join("/"),
                      )
                    }
                  >
                    {p}
                  </button>
                </span>
              ))}
          </div>
          <div className="rag-folder-search">
            <Search size={16} />
            <input
              aria-label="현재 폴더 파일명 검색"
              placeholder="현재 폴더에서 이름 검색"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
          <div className="rag-browser-list">
            {path && (
              <button
                className="rag-entry"
                onClick={() => setPath(path.split("/").slice(0, -1).join("/"))}
              >
                <ArrowLeft size={17} />
                <span>상위 폴더</span>
              </button>
            )}
            {entries.map((e) => (
              <button
                key={e.name}
                className="rag-entry"
                disabled={e.kind !== "directory" || !!e.reason}
                onClick={() => {
                  setPath([path, e.name].filter(Boolean).join("/"));
                  setFilter("");
                }}
              >
                {e.kind === "directory" ? (
                  <Folder size={19} />
                ) : (
                  <FileText size={17} />
                )}
                <span>
                  {e.name}
                  {e.reason && <small>{reasons[e.reason] || e.reason}</small>}
                </span>
                {e.kind === "directory" && !e.reason && (
                  <ChevronRight size={15} />
                )}
              </button>
            ))}
            {root && !entries.length && (
              <div className="rag-small-empty">표시할 항목이 없습니다.</div>
            )}
            {cursor !== null && (
              <button className="rag-text-button" onClick={loadMore}>
                더 보기
              </button>
            )}
          </div>
          <div className="rag-browser-footer">
            <span>MD · TXT · CSV · TSV · XLSX</span>
            <button
              className="rag-primary"
              disabled={!root || loading}
              onClick={choose}
            >
              <Check size={16} />이 폴더 사용
            </button>
          </div>
        </section>
        <section className="rag-panel rag-create-summary">
          <h2>새 워크스페이스</h2>
          <label htmlFor="rag-name">이름</label>
          <input
            id="rag-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="예: 프로젝트 운영 자료"
            maxLength={100}
          />
          <label>선택한 폴더</label>
          <div className="rag-chosen-folder">
            <Folder size={18} />
            {chosen
              ? `${roots.find((r) => r.id === chosen.root_id)?.label} / ${chosen.relative_path || "전체 폴더"}`
              : "왼쪽에서 폴더를 선택하세요."}
          </div>
          {preview && (
            <>
              <div className="rag-preview-status">
                <Badge state={preview.state} />
                <span>
                  {preview.result.files?.filter((f) => f.state === "INCLUDED")
                    .length ?? 0}
                  개 문서
                </span>
              </div>
              <Files files={preview.result.files} />
              {preview.result.error_code && (
                <p className="rag-inline-error">
                  {preview.result.message || preview.result.error_code}
                </p>
              )}
            </>
          )}
          <button
            className="rag-primary rag-full"
            disabled={
              !name.trim() ||
              loading ||
              preview?.state !== "READY" ||
              !preview.result.files?.some((f) => f.state === "INCLUDED")
            }
            onClick={create}
          >
            {loading ? (
              <Loader2 size={17} className="rag-spin" />
            ) : (
              <Database size={17} />
            )}
            문서 연결
          </button>
          <p className="rag-footnote">
            브라우저를 닫아도 자료 준비가 계속됩니다. 미리보기 이후 변경된
            파일은 준비 단계에서 다시 확인합니다.
          </p>
        </section>
      </div>
    </>
  );
}
