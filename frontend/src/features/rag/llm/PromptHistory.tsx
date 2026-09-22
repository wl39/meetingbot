import { History } from "lucide-react";
import { dates } from "./format";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function PromptHistory({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    | "listing"
    | "view"
    | "busy"
    | "run"
    | "selectPrompt"
    | "editViewedPrompt"
    | "applyVersion"
  >;
}) {
  const {
    listing,
    view,
    busy,
    run,
    selectPrompt,
    editViewedPrompt,
    applyVersion,
  } = settings;
  return (
    <aside className="rag-panel rag-ai-history">
      <h2>
        <History size={18} />
        버전 기록
      </h2>
      <p>활성 버전은 새 답변에 적용됩니다.</p>
      <div className="rag-ai-version-list">
        {listing.versions.map((p) => (
          <button
            key={p.id}
            className={view?.id === p.id ? "selected" : ""}
            disabled={!!busy}
            onClick={() => selectPrompt(p.id)}
          >
            <strong>
              v{p.sequence} {listing.active_id === p.id && <em>활성</em>}
            </strong>
            <span>{p.name}</span>
            <small>{dates(p.created_at)}</small>
          </button>
        ))}
      </div>
      {view && (
        <div className="rag-ai-version-detail">
          <h3>v{view.sequence} 내용</h3>
          <p>{view.note || "변경 메모 없음"}</p>
          <details>
            <summary>저장된 지침 보기</summary>
            <pre>{view.content}</pre>
          </details>
          <button
            className="rag-secondary"
            disabled={!!busy}
            onClick={editViewedPrompt}
          >
            편집기로 불러오기
          </button>
          <button
            className="rag-secondary"
            disabled={!!busy || view.id === listing.active_id}
            onClick={() => run("버전 적용 중…", () => applyVersion(false))}
          >
            이 버전 적용
          </button>
          <button
            className="rag-secondary"
            disabled={!!busy}
            onClick={() =>
              run("이전 내용으로 복원 중…", () => applyVersion(true))
            }
          >
            이 내용으로 새 버전 복원
          </button>
        </div>
      )}
    </aside>
  );
}
