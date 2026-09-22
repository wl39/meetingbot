import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  FileText,
  History,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";
import { FeedbackMessage } from "../../../components/ui/FeedbackMessage";
import { useWorkspace } from "../../../workspace/context";
import {
  api,
  locationLabel,
  RagApiError,
  type Evidence,
  type SearchResult,
} from "../api";
import MarkdownView from "../components/MarkdownView";
import EvidencePanel from "../workspace/EvidencePanel";
import { message, time } from "../utils";
import {
  historyStatus,
  type HistoryDetail,
  type HistoryFilters,
  type HistoryPage,
} from "./types";
import "./history.css";
import { forgetQuestion, lastQuestion, rememberQuestion } from "./bookmark";
import QuestionProgress, { questionPending } from "./QuestionProgress";

const emptyFilters = {
  q: "",
  subject: "",
  workspace_id: "",
  kind: "",
  from: "",
  to: "",
};
const legacyLabel = "이전 기록 · 계정 미확인";

export default function QuestionHistory({
  all = false,
  onContinue,
}: {
  all?: boolean;
  onContinue: (result: SearchResult) => void;
}) {
  const { access } = useWorkspace();
  const scope = all ? "all" : "mine";
  const accountId = access.account?.id;
  const [bookmark, setBookmark] = useState(() =>
    lastQuestion(accountId, scope),
  );
  const [draft, setDraft] = useState(emptyFilters);
  const [filters, setFilters] = useState(emptyFilters);
  const [options, setOptions] = useState<HistoryFilters>({
    accounts: [],
    workspaces: [],
  });
  const [page, setPage] = useState<HistoryPage | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(
    () => new URL(location.href).searchParams.get("question") || "",
  );
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [detailError, setDetailError] = useState("");
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const allowed =
    !all || access.role === "admin" || access.role === "superadmin";

  useEffect(() => {
    const sync = () => setBookmark(lastQuestion(accountId, scope));
    sync();
    window.addEventListener("storage", sync);
    window.addEventListener("focus", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("focus", sync);
    };
  }, [accountId, scope]);

  useEffect(() => {
    if (!allowed) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      scope,
      offset: String(offset),
      limit: "25",
    });
    for (const key of ["q", "subject", "workspace_id", "kind"] as const)
      if (filters[key]) params.set(key, filters[key]);
    if (filters.from)
      params.set(
        "since",
        String(new Date(filters.from + "T00:00:00").getTime() / 1000),
      );
    if (filters.to) {
      const end = new Date(filters.to + "T00:00:00");
      end.setDate(end.getDate() + 1);
      params.set("until", String(end.getTime() / 1000));
    }
    setLoading(true);
    setError("");
    Promise.all([
      api<HistoryPage>(
        `/history?${params}`,
        undefined,
        undefined,
        controller.signal,
      ),
      api<HistoryFilters>(
        `/history/filters?scope=${scope}`,
        undefined,
        undefined,
        controller.signal,
      ),
    ])
      .then(([records, choices]) => {
        if (!controller.signal.aborted) {
          setPage(records);
          setOptions(choices);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(message(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accountId, scope, allowed, filters, offset, refresh]);

  useEffect(() => {
    if (selected || !page?.items.some((item) => questionPending(item.status)))
      return;
    const timer = setTimeout(() => setRefresh((value) => value + 1), 4000);
    return () => clearTimeout(timer);
  }, [selected, page]);

  useEffect(() => {
    setDetail(null);
    setDetailError("");
    setEvidence(null);
    if (!selected || !allowed) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = () =>
      api<HistoryDetail>(
        `/history/${encodeURIComponent(selected)}?scope=${scope}`,
        undefined,
        undefined,
        controller.signal,
      )
        .then((value) => {
          if (controller.signal.aborted) return;
          setDetail(value);
          setDetailError("");
          rememberQuestion(accountId, scope, value.id);
          setBookmark(lastQuestion(accountId, scope));
          if (questionPending(value.result.status))
            timer = setTimeout(() => void load(), 2000);
        })
        .catch((e) => {
          if (controller.signal.aborted) return;
          setDetailError(message(e));
          if (e instanceof RagApiError && e.code === "NOT_FOUND") {
            forgetQuestion(accountId, scope, selected);
            setBookmark(lastQuestion(accountId, scope));
          }
          if (!(e instanceof RagApiError && [401, 403, 404].includes(e.status)))
            timer = setTimeout(() => void load(), 4000);
        });
    void load();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [selected, accountId, scope, allowed, refresh]);

  useEffect(() => {
    const restore = () =>
      setSelected(new URL(location.href).searchParams.get("question") || "");
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  function select(id: string) {
    setSelected(id);
    const url = new URL(location.href);
    if (id) url.searchParams.set("question", id);
    else url.searchParams.delete("question");
    window.history.replaceState(null, "", url.pathname + url.search);
  }
  if (!allowed)
    return (
      <FeedbackMessage className="rag-alert" tone="error">
        전체 질문 기록은 관리자만 확인할 수 있습니다.
      </FeedbackMessage>
    );

  return (
    <section
      className="rag-query-history"
      aria-label={all ? "전체 질문 기록" : "내 질문 기록"}
    >
      <header className="rag-title-row">
        <div>
          <h1>{all ? "전체 질문 기록" : "내 질문 기록"}</h1>
          <p>
            {all
              ? "계정별 질문, 답변과 검색 자료를 확인하세요."
              : "이전에 물어본 질문과 답변을 다시 확인하세요."}
          </p>
          <p className="query-history-retention">
            최근 {page?.retention_days ?? 30}일 동안의 질문을 확인할 수
            있습니다.
            {!all && access.account ? ` · ${access.account.label}` : ""}
          </p>
          {!all && (
            <p className="query-history-retention">
              질문과 답변은 저장되며 관리자가 확인할 수 있습니다.
            </p>
          )}
        </div>
        <button
          className="rag-secondary"
          onClick={() => setRefresh((n) => n + 1)}
          disabled={loading}
        >
          <RefreshCw size={16} />
          기록 새로고침
        </button>
      </header>
      {selected ? (
        <>
          <button className="rag-secondary" onClick={() => select("")}>
            <ArrowLeft size={16} />
            기록 목록
          </button>
          {detailError ? (
            <FeedbackMessage
              className="rag-alert query-history-detail-status"
              tone="error"
            >
              {detailError}
            </FeedbackMessage>
          ) : !detail ? (
            <p className="query-history-detail-status" role="status">
              <Loader2 className="rag-spin" size={18} />
              기록을 불러오는 중…
            </p>
          ) : (
            <article className="query-history-detail">
              <div className="query-history-meta">
                <span>{detail.workspace_name || "이름 없는 자료"}</span>
                <time>{time(detail.created_at)}</time>
                <span>
                  {detail.kind === "search" ? "문서 검색" : "AI 질문"}
                </span>
                <span>
                  {historyStatus[detail.result.status] || "확인 필요"}
                </span>
              </div>
              {all && (
                <p className="query-history-account">
                  {detail.account_label || legacyLabel}
                  <small>계정 ID: {detail.subject || "기록되지 않음"}</small>
                </p>
              )}
              <h2>{detail.result.query}</h2>
              {questionPending(detail.result.status) ? (
                <QuestionProgress result={detail.result} />
              ) : (
                <div className="rag-answer">
                  <h3>
                    {historyStatus[detail.result.status] || "저장된 답변"}
                  </h3>
                  <MarkdownView
                    text={
                      detail.result.answer ||
                      (detail.kind === "search"
                        ? "아래 검색 결과를 확인하세요."
                        : "저장된 답변이 없습니다.")
                    }
                  />
                </div>
              )}
              <section
                className="query-history-sources"
                aria-label="저장된 출처"
              >
                <h3>
                  {detail.kind === "search"
                    ? "검색 결과"
                    : "답변에 사용한 출처"}
                </h3>
                {detail.result.evidence
                  .filter(
                    (e) =>
                      detail.kind === "search" ||
                      detail.result.citations?.includes(e.evidence_id),
                  )
                  .map((e) => (
                    <button key={e.evidence_id} onClick={() => setEvidence(e)}>
                      <FileText size={18} />
                      <span>
                        <strong>{e.relative_path.normalize("NFC")}</strong>
                        <small>{locationLabel(e)}</small>
                        <p>{e.text.slice(0, 220)}</p>
                      </span>
                      <ChevronRight size={16} />
                    </button>
                  ))}
                {!detail.result.citations?.length &&
                  detail.kind !== "search" && <p>인용된 출처가 없습니다.</p>}
              </section>
              <div className="query-history-footer">
                <button
                  className="rag-primary"
                  onClick={() => onContinue(detail.result)}
                >
                  이 자료에서 이어 질문하기
                  <ChevronRight size={16} />
                </button>
              </div>
            </article>
          )}
        </>
      ) : (
        <>
          {bookmark && (
            <button
              className="rag-secondary query-history-resume"
              onClick={() => select(bookmark)}
            >
              <History size={16} />
              마지막 질문 다시 보기
            </button>
          )}
          <form
            className="query-history-filters"
            onSubmit={(e) => {
              e.preventDefault();
              setOffset(0);
              setFilters({ ...draft });
            }}
          >
            <label className="query-history-keyword">
              질문·답변 검색
              <input
                aria-label="질문·답변 검색"
                value={draft.q}
                onChange={(e) => setDraft({ ...draft, q: e.target.value })}
                placeholder="검색어를 입력하세요"
                maxLength={500}
              />
            </label>
            {all && (
              <label>
                계정
                <select
                  aria-label="계정"
                  value={draft.subject}
                  onChange={(e) =>
                    setDraft({ ...draft, subject: e.target.value })
                  }
                >
                  <option value="">모든 계정</option>
                  {options.accounts.map((a) => (
                    <option
                      key={a.subject || "legacy"}
                      value={a.subject || "legacy"}
                    >
                      {a.label || legacyLabel}
                      {a.subject ? ` · ${a.subject.slice(0, 12)}` : ""} (
                      {a.count})
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label>
              자료
              <select
                aria-label="자료"
                value={draft.workspace_id}
                onChange={(e) =>
                  setDraft({ ...draft, workspace_id: e.target.value })
                }
              >
                <option value="">모든 자료</option>
                {options.workspaces.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name || w.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              유형
              <select
                aria-label="유형"
                value={draft.kind}
                onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
              >
                <option value="">질문과 검색</option>
                <option value="question">AI 질문</option>
                <option value="search">문서 검색</option>
              </select>
            </label>
            <label>
              시작일
              <input
                aria-label="시작일"
                type="date"
                value={draft.from}
                max={draft.to || undefined}
                onChange={(e) => setDraft({ ...draft, from: e.target.value })}
              />
            </label>
            <label>
              종료일
              <input
                aria-label="종료일"
                type="date"
                value={draft.to}
                min={draft.from || undefined}
                onChange={(e) => setDraft({ ...draft, to: e.target.value })}
              />
            </label>
            <button className="rag-primary" disabled={loading}>
              <Search size={16} />
              기록 검색
            </button>
          </form>
          {error && (
            <FeedbackMessage className="rag-alert" tone="error">
              {error}
            </FeedbackMessage>
          )}
          {loading ? (
            <p className="query-history-empty" role="status">
              <Loader2 size={18} className="rag-spin" />
              기록을 불러오는 중…
            </p>
          ) : (
            <>
              <p className="query-history-count">총 {page?.total ?? 0}건</p>
              <div className="query-history-list">
                {page?.items.map((entry) => (
                  <button
                    key={entry.id}
                    className="query-history-row"
                    onClick={() => select(entry.id)}
                  >
                    <div className="query-history-meta">
                      <span>
                        {entry.kind === "search" ? "문서 검색" : "AI 질문"}
                      </span>
                      <span>{entry.workspace_name || "이름 없는 자료"}</span>
                      <time>{time(entry.created_at)}</time>
                    </div>
                    {all && (
                      <div className="query-history-account">
                        {entry.account_label || legacyLabel}
                        <small>{entry.subject || "계정 ID 없음"}</small>
                      </div>
                    )}
                    <strong>{entry.query}</strong>
                    <p>
                      {entry.answer_preview ||
                        (entry.kind === "search"
                          ? "저장된 검색 결과 보기"
                          : "답변 기록 보기")}
                    </p>
                    <span className="query-history-status">
                      {historyStatus[entry.status] || "확인 필요"}
                      <ChevronRight size={15} />
                    </span>
                  </button>
                ))}
              </div>
              {!page?.items.length && (
                <p className="query-history-empty">
                  {page?.total
                    ? "이 페이지에 표시할 기록이 없습니다."
                    : "조건에 맞는 질문 기록이 없습니다."}
                </p>
              )}
              {!!page?.total && (
                <nav
                  className="query-history-pagination"
                  aria-label="질문 기록 페이지"
                >
                  <button
                    className="rag-secondary"
                    disabled={!offset}
                    onClick={() => setOffset((n) => Math.max(0, n - 25))}
                  >
                    <ChevronLeft size={16} />
                    이전
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + 25, page.total)} /{" "}
                    {page.total}건
                  </span>
                  <button
                    className="rag-secondary"
                    disabled={offset + 25 >= page.total}
                    onClick={() => setOffset((n) => n + 25)}
                  >
                    다음
                    <ChevronRight size={16} />
                  </button>
                </nav>
              )}
            </>
          )}
        </>
      )}
      {evidence && (
        <EvidencePanel
          key={evidence.evidence_id}
          evidence={evidence}
          onClose={() => setEvidence(null)}
        />
      )}
    </section>
  );
}
