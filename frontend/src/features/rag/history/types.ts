import type { SearchResult } from "../api";

export type HistorySummary = {
  id: string;
  workspace_id: string;
  workspace_name: string | null;
  created_at: number;
  subject: string | null;
  account_label: string | null;
  account_role: string | null;
  kind: "question" | "search";
  query: string;
  status: string;
  answer_preview: string;
};
export type HistoryDetail = HistorySummary & { result: SearchResult };
export type HistoryPage = {
  items: HistorySummary[];
  total: number;
  limit: number;
  offset: number;
  retention_days: number;
};
export type HistoryFilters = {
  accounts: {
    subject: string | null;
    label: string | null;
    role: string | null;
    count: number;
  }[];
  workspaces: { id: string; name: string | null }[];
};
export const historyStatus: Record<string, string> = {
  answered: "답변 완료",
  related_evidence: "관련 자료 기반 안내",
  conflicting_evidence: "상충 자료 안내",
  insufficient_evidence: "근거 부족",
  found: "검색 완료",
  processing: "처리 중",
  queued: "처리 대기 중",
  failed: "요청 실패",
  llm_unavailable: "답변 미완료",
  aggregation_unsupported: "원문 확인 필요",
};
