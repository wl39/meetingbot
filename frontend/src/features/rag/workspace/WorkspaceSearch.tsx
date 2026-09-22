import {
  ArrowUpRight,
  BookOpen,
  ChevronRight,
  FileText,
  Layers,
  Loader2,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { locationLabel, reasons, type Diagnostics } from "../api";
import FilePath from "../components/FilePath";
import MarkdownView from "../components/MarkdownView";
import EvidencePreview from "../components/EvidencePreview";
import { time } from "../utils";
import type { WorkspaceDetail } from "./useWorkspaceDetail";
import { useWorkspace } from "../../../workspace/context";
import { historyStatus } from "../history/types";
import QuestionProgress, { questionPending } from "../history/QuestionProgress";

export default function WorkspaceSearch({
  workspace,
  diagnostics,
  managesData,
  managesAI,
  onManageAI,
}: {
  diagnostics: Diagnostics | null;
  managesData: boolean;
  managesAI: boolean;
  onManageAI: () => void;
  workspace: Pick<
    WorkspaceDetail,
    | "ws"
    | "revision"
    | "revisions"
    | "query"
    | "searching"
    | "searchAction"
    | "result"
    | "history"
    | "setQuery"
    | "setEvidence"
    | "search"
    | "selectRevision"
    | "selectHistory"
  >;
}) {
  const { navigate, access } = useWorkspace();
  const {
    ws,
    revision,
    revisions,
    query,
    searching,
    searchAction,
    result,
    history,
    setQuery,
    setEvidence,
    search,
    selectRevision,
    selectHistory,
  } = workspace;
  const llm = diagnostics?.llm;
  const needsApproval = !!llm && ws.consent !== llm.provider_id;
  const canAnswer =
    !!llm?.global_allowed &&
    !!llm.configured &&
    (!needsApproval || managesData);
  const answer = () =>
    search(true, needsApproval ? llm?.provider_id : undefined);
  return (
    <div className="rag-search-layout">
      <section>
        <div className="rag-panel rag-search-panel">
          <div className="rag-panel-heading">
            <h2>문서에 질문하기</h2>
            <select
              aria-label="검색 자료 버전"
              value={revision}
              onChange={(e) => selectRevision(e.target.value)}
            >
              <option value="">최신 문서</option>
              {revisions
                .filter((r) => r.state === "READY")
                .map((r) => (
                  <option value={r.id} key={r.id}>
                    {time(r.created_at)} 등록
                  </option>
                ))}
            </select>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (canAnswer) void answer();
            }}
          >
            <div className="rag-query">
              <Search size={22} />
              <textarea
                aria-label="검색 질문"
                value={query}
                maxLength={8000}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="확인할 내용을 질문하세요. 문서에서 답변과 출처를 찾아드립니다."
                rows={3}
              />
            </div>
            <div className="rag-search-actions">
              <span>
                <ShieldCheck size={15} />
                {llm && !canAnswer
                  ? "질문 기능을 준비하고 있습니다. 문서 검색은 계속 이용할 수 있습니다."
                  : "등록된 문서를 바탕으로 답변하고, 확인에 사용한 출처를 함께 제공합니다."}
              </span>
              <div>
                <button
                  type="submit"
                  className="rag-primary"
                  disabled={
                    !query.trim() ||
                    searching ||
                    !ws.active_revision_id ||
                    !canAnswer
                  }
                >
                  {searchAction === "answer" ? (
                    <Loader2 size={16} className="rag-spin" />
                  ) : (
                    <Sparkles size={16} />
                  )}
                  {searchAction === "answer" ? "질문 접수 중…" : "질문하기"}
                </button>
                <button
                  type="button"
                  className="rag-secondary"
                  onClick={() => void search()}
                  disabled={
                    !query.trim() || searching || !ws.active_revision_id
                  }
                >
                  {searchAction === "search" ? (
                    <Loader2 size={17} className="rag-spin" />
                  ) : (
                    <Search size={17} />
                  )}
                  {searchAction === "search" ? "문서 검색 중…" : "문서 검색"}
                </button>
              </div>
            </div>
          </form>
          <p className="query-history-notice">
            질문과 답변은 내 질문 기록에 저장되며 관리자가 확인할 수 있습니다.
            {diagnostics &&
              ` 보관 기간: ${access.demo ? Math.min(1, diagnostics.history_days) : diagnostics.history_days}일.`}
          </p>
          {llm && (!llm.global_allowed || !llm.configured) && managesAI && (
            <button className="rag-secondary" onClick={onManageAI}>
              서비스 설정 확인
            </button>
          )}
        </div>
        {searching && (
          <p className="rag-search-progress" role="status">
            {searchAction === "answer"
              ? "질문을 접수하고 있습니다."
              : "관련 문서를 검색하고 있습니다."}
          </p>
        )}
        {result && questionPending(result.status) ? (
          <QuestionProgress result={result} />
        ) : result ? (
          <>
            <div className="rag-result-heading">
              <h2>
                관련 문서 <span>{result.evidence.length}</span>
              </h2>
            </div>
            {result.answer && (
              <div className="rag-answer">
                <h3>
                  <Sparkles size={18} />
                  {result.status === "answered"
                    ? "문서 기반 답변"
                    : result.status === "related_evidence"
                      ? "관련 자료 기반 안내"
                      : result.status === "conflicting_evidence"
                        ? "문서 간 내용이 다릅니다"
                        : "확인이 필요합니다"}
                </h3>
                <MarkdownView
                  text={
                    result.reason
                      ? reasons[result.reason] ||
                        "답변을 완성하지 못했습니다. 관련 문서를 확인하거나 잠시 후 다시 질문해 주세요."
                      : result.answer
                  }
                />
                {result.reason === "EXTERNAL_LLM_NOT_APPROVED" && (
                  <div className="rag-answer-actions">
                    {canAnswer ? (
                      <button
                        className="rag-primary"
                        disabled={searching || !query.trim()}
                        onClick={() => void answer()}
                      >
                        다시 질문하기
                      </button>
                    ) : managesAI ? (
                      <button className="rag-secondary" onClick={onManageAI}>
                        서비스 설정 확인
                      </button>
                    ) : (
                      <p>
                        관리자에게 이 워크스페이스의 이용 설정을 문의해 주세요.
                      </p>
                    )}
                  </div>
                )}
                {result.reason &&
                  result.reason !== "EXTERNAL_LLM_NOT_APPROVED" &&
                  managesAI && (
                    <button className="rag-secondary" onClick={onManageAI}>
                      서비스 설정 확인
                    </button>
                  )}
                {result.citations?.length ? (
                  <div className="rag-citations">
                    {result.citations.map((id, i) => (
                      <button
                        key={id}
                        onClick={() =>
                          setEvidence(
                            result.evidence.find((e) => e.evidence_id === id) ||
                              null,
                          )
                        }
                      >
                        근거{" "}
                        {result.evidence.findIndex(
                          (e) => e.evidence_id === id,
                        ) + 1 || i + 1}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            )}
            {!result.evidence.length ? (
              <div className="rag-empty-search">
                <Search size={27} />
                <h3>선택한 자료에서 확인할 수 없습니다.</h3>
                <p>다른 표현으로 검색하거나 자료를 추가해 보세요.</p>
              </div>
            ) : (
              result.evidence.map((e, i) => (
                <article className="rag-evidence-card" key={e.evidence_id}>
                  <div className="rag-evidence-top">
                    <span className="rag-evidence-number">{i + 1}</span>
                    <div>
                      <FilePath path={e.relative_path} />
                      <small>
                        {e.title_path.join(" / ") || "문서 본문"} ·{" "}
                        {locationLabel(e)}
                      </small>
                    </div>
                    <button onClick={() => setEvidence(e)}>
                      원문 보기
                      <ArrowUpRight size={15} />
                    </button>
                  </div>
                  {/\.md$/i.test(e.relative_path) ? (
                    <EvidencePreview evidence={e} />
                  ) : (
                    <p>{e.text}</p>
                  )}
                  {e.table && (
                    <small className="rag-footnote">
                      질문과 관련된 표의 일부입니다. 전체 내용은 원문에서
                      확인하세요.
                    </small>
                  )}
                </article>
              ))
            )}
          </>
        ) : !searching ? (
          <div className="rag-empty-search">
            <span>
              <BookOpen size={33} />
            </span>
            <h3>
              {ws.active_revision_id
                ? "문서에서 답을 찾아보세요"
                : "문서를 준비하고 있습니다"}
            </h3>
            <p>
              {ws.active_revision_id
                ? "업무 기준, 의사결정의 배경, 확인이 필요한 내용을 질문하세요."
                : "준비가 완료되면 질문과 문서 검색을 이용할 수 있습니다."}
            </p>
            {ws.active_revision_id && (
              <button
                onClick={() =>
                  setQuery("이 문서에서 꼭 알아야 할 내용은 무엇인가요?")
                }
              >
                이 문서의 핵심 내용은 무엇인가요?
                <ArrowUpRight size={14} />
              </button>
            )}
          </div>
        ) : null}
      </section>
      <aside className="rag-search-aside">
        <div className="rag-panel rag-tips">
          <h3>문서로 확인하는 답변</h3>
          <p>
            선택한 워크스페이스의 문서를 참고합니다. 답변 아래에서 출처와 원문을
            확인할 수 있습니다.
          </p>
          <hr />
          <div>
            <FileText size={17} />
            <span>답변에 사용한 출처 확인</span>
          </div>
          <div>
            <Layers size={17} />
            <span>문서와 표를 원문으로 열람</span>
          </div>
          <div>
            <ShieldCheck size={17} />
            <span>회의 내용과 문서의 일치 여부 검토</span>
          </div>
        </div>
        <div className="rag-history">
          <h3>내 최근 질문·검색</h3>
          {history.length ? (
            history.slice(0, 8).map((h) => (
              <button key={h.request_id} onClick={() => selectHistory(h)}>
                {h.query}
                <small>
                  {historyStatus[h.status] || "문서 확인"}
                  {h.created_at ? ` · ${time(h.created_at)}` : ""}
                </small>
              </button>
            ))
          ) : (
            <p>질문한 내용이 여기에 모입니다.</p>
          )}
          <button onClick={() => navigate("/rag/history")}>
            내 질문 기록 전체 보기 <ChevronRight size={14} />
          </button>
        </div>
      </aside>
    </div>
  );
}
