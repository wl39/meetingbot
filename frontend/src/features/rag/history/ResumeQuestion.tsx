import { useEffect, useState } from "react";
import { ChevronRight, History } from "lucide-react";
import { useWorkspace } from "../../../workspace/context";
import { api, RagApiError, type SearchResult } from "../api";
import { time } from "../utils";
import { forgetQuestion, lastQuestion } from "./bookmark";
import type { HistoryDetail } from "./types";
import "./history.css";

export default function ResumeQuestion({
  onContinue,
}: {
  onContinue: (result: SearchResult) => void;
}) {
  const { access } = useWorkspace();
  const accountId = access.account?.id;
  const [detail, setDetail] = useState<HistoryDetail | null>(null);

  useEffect(() => {
    setDetail(null);
    if (!accountId) return;
    const id = lastQuestion(accountId, "mine");
    if (!id) return;
    const controller = new AbortController();
    api<HistoryDetail>(
      `/history/${encodeURIComponent(id)}?scope=mine`,
      undefined,
      undefined,
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted && value.subject === accountId)
          setDetail(value);
      })
      .catch((error) => {
        if (
          !controller.signal.aborted &&
          error instanceof RagApiError &&
          error.code === "NOT_FOUND"
        )
          forgetQuestion(accountId, "mine", id);
      });
    return () => controller.abort();
  }, [accountId]);

  if (!detail || detail.subject !== accountId) return null;
  return (
    <section className="query-history-resume" aria-label="마지막 질문 이어보기">
      <History size={21} aria-hidden="true" />
      <div>
        <strong>마지막 질문 이어보기</strong>
        <p>{detail.result.query}</p>
        <small>{detail.workspace_name} · {time(detail.created_at)}</small>
      </div>
      <button className="rag-secondary" onClick={() => onContinue(detail.result)}>
        저장된 답변 열기 <ChevronRight size={16} />
      </button>
    </section>
  );
}
