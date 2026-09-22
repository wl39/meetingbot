import type { Diagnostics, Evidence, Workspace } from "../rag/api";

export type PopupKind = "warning" | "caution" | "info" | "success";
export type MeetingResult = {
  workspace_id: string;
  session_id: string;
  utterance_id: string;
  utterance_revision: number;
  revision_id: string;
  request_id: string;
  status:
    | "popup"
    | "suppressed"
    | "insufficient_evidence"
    | "unavailable"
    | "needs_clarification"
    | "unsupported_action";
  reason?: string;
  message?: string;
  analysis?: {
    keywords: string[];
    query: string;
    intent: string;
    claim: string;
  };
  popup: null | {
    id: string;
    kind: PopupKind;
    color: "red" | "orange" | "blue" | "green";
    title: string;
    message: string;
    confidence: number;
    citations: string[];
  };
  evidence: Evidence[];
  timings_ms: Record<string, number>;
};

export function readiness(
  workspace: Workspace | undefined,
  diagnostics: Diagnostics | null,
  allowActivation = false,
) {
  if (!diagnostics) return "자료 연결 상태를 확인해 주세요.";
  if (!workspace) return "참고할 문서가 있는 워크스페이스를 선택하세요.";
  if (!workspace.active_revision_id)
    return "선택한 워크스페이스의 자료를 먼저 준비해 주세요.";
  if (workspace.access_state && workspace.access_state !== "AVAILABLE")
    return "자료 설정에서 원본 파일의 접근 권한을 확인해 주세요.";
  if (diagnostics.model.state !== "READY")
    return "자료 검색을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.";
  if (!diagnostics.llm.configured)
    return "회의 검토 서비스를 준비하고 있습니다. 관리자에게 문의해 주세요.";
  if (!diagnostics.llm.global_allowed)
    return "회의 검토 기능이 비활성화되어 있습니다. 관리자에게 문의해 주세요.";
  if (workspace.consent !== diagnostics.llm.provider_id && !allowActivation)
    return "이 워크스페이스의 회의 검토를 준비하고 있습니다. 관리자에게 문의해 주세요.";
  return "";
}

export function safeManageUrl(value?: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

export function reasonMessage(reason?: string) {
  const messages: Record<string, string> = {
    NEEDS_CONTEXT: "어떤 내용을 확인하고 싶은지 조금 더 자세히 알려주세요.",
    LOW_PRIORITY_RECORDED: "대화가 기록되었습니다.",
    MEETING_CAPACITY:
      "검토 작업이 많아 접수가 지연되고 있습니다. 기존 작업은 보존됩니다.",
    SOURCE_OR_CONSENT_CHANGED:
      "문서 버전이나 이용 동의가 바뀌었습니다. 설정을 확인한 뒤 검토를 다시 시작해 주세요.",
    FILTER_TIMEOUT:
      "내용을 확인하는 데 시간이 걸리고 있습니다. 다시 시도해 주세요.",
    FILTER_FAILED: "내용을 확인하지 못했습니다. 다시 시도해 주세요.",
    MEETING_POLICY_CONFLICT:
      "설정이 변경되었습니다. 다시 불러온 뒤 수정해 주세요.",
    SUBSCRIPTION_DISABLED:
      "검토가 종료되었습니다. 검토를 시작한 후 다시 시도해 주세요.",
    MEETING_SUBSCRIPTION_DISABLED:
      "검토가 종료되었습니다. 검토를 시작한 후 다시 시도해 주세요.",
    ROLE_DENIED: "이 작업을 수행할 권한이 없습니다.",
    FILTER_UNAVAILABLE:
      "문서 참고를 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    NO_RELEVANT_INFORMATION: "추가로 안내할 내용이 없습니다.",
    NO_SUPPORT: "관련 문서 근거가 부족해 판단을 보류했습니다.",
    EXTERNAL_LLM_NOT_APPROVED:
      "문서 이용 설정이 변경되었습니다. 회의 검토를 다시 시작해 주세요.",
    PROXY_NOT_CONFIGURED:
      "회의 검토 서비스를 준비하고 있습니다. 관리자에게 문의해 주세요.",
    RAG_TIMEOUT: "자료 검색에 시간이 걸리고 있습니다. 다시 시도해 주세요.",
    RAG_UNAVAILABLE: "자료 검색에 연결할 수 없습니다.",
    RAG_CREDENTIAL_UNAVAILABLE:
      "자료 연결을 확인할 수 없습니다. 관리자에게 문의해 주세요.",
    RAG_INVALID_RESPONSE:
      "검색 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    LLM_BUSY: "다른 내용을 검토하고 있습니다. 잠시 후 다시 시도해 주세요.",
    SEARCH_BUSY: "다른 문서 검색이 진행 중입니다.",
    PROXY_UNAVAILABLE: "회의 검토에 일시적으로 연결하지 못했습니다.",
    PROXY_RATE_LIMIT: "이용량이 많아 검토가 지연되고 있습니다.",
    NO_RELEVANT_CLAIM: "추가로 안내할 내용이 없습니다.",
    NO_ACTIONABLE_CONTENT: "추가로 안내할 내용이 없습니다.",
    NO_EVIDENCE: "관련 문서 근거가 부족해 판단을 보류했습니다.",
    INSUFFICIENT_EVIDENCE: "관련 문서 근거가 부족해 판단을 보류했습니다.",
    LOW_CONFIDENCE: "근거가 명확하지 않아 판단을 보류했습니다.",
    STALE_UTTERANCE: "발화가 수정되어 최신 내용을 다시 기다립니다.",
  };
  return reason
    ? (messages[reason] ??
        "내용을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.")
    : "관련 문서를 확인했습니다.";
}
