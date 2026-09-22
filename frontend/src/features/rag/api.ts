import { accessHeaders } from "../../workspace/access";
export type Workspace = {
  can_manage?: boolean;
  visibility?: "private" | "shared";
  id: string;
  name: string;
  description: string;
  state: string;
  document_count: number;
  active_revision_id: string | null;
  consent: string | null;
  access_state?: string;
  source: {
    root_id: string;
    relative_path: string;
    kind?: "upload" | "server";
    label?: string;
  } | null;
  latest_job: Job | null;
};
export type WorkspaceGuide = {
  workspace_id: string;
  content: string;
  enabled: boolean;
  version: number;
  content_hash: string;
  updated_at: number | null;
  max_chars: number;
};
export type SourceFile = {
  relative_path: string;
  state: string;
  reason?: string;
  bytes?: number;
  reused?: boolean;
  warnings?: { code: string; sheet: string }[];
};
export type Job = {
  job_id: string;
  state: string;
  revision_id: string | null;
  workspace_id: string | null;
  cancel: number;
  result: {
    stage?: string;
    review_accepted?: boolean;
    files?: SourceFile[];
    scanned?: number;
    documents?: unknown[];
    chunks?: number;
    embedded_chunks?: number;
    reused_documents?: number;
    error_code?: string;
    message?: string;
    timings_ms?: Record<string, number>;
  };
};
export type Cell = {
  address: string;
  value: unknown;
  display?: unknown;
  formula?: string | null;
  formula_status?: string | null;
  number_format?: string;
  type: string;
};
export type Evidence = {
  source_preview?: boolean;
  evidence_id: string;
  workspace_id: string;
  revision_id: string;
  relative_path: string;
  text: string;
  title_path: string[];
  location: {
    type: string;
    start_line?: number;
    end_line?: number;
    sheet?: string;
    start_row?: number;
    end_row?: number;
    cell_range?: string;
  };
  table?: { headers: string[]; cells: Cell[] };
};
export type SearchResult = {
  created_at?: number;
  kind?: "question" | "search";
  workspace_id: string;
  revision_id: string;
  request_id: string;
  query: string;
  status: string;
  evidence: Evidence[];
  answer?: string;
  reason?: string;
  citations?: string[];
  llm?: {
    model: string;
    prompt_version: number;
    prompt_id: string;
    settings_version: number;
  };
  timings_ms: Record<string, number>;
};
export type Diagnostics = {
  model: {
    state: string;
    model: string;
    revision: string;
    device: string;
    dimension: number;
    error_code?: string;
  };
  llm: {
    global_allowed: boolean;
    provider_id: string;
    endpoint: string;
    model: string;
    configured: boolean;
    scope: string;
  };
  access_mode: string;
  history_days: number;
  versions: string;
  limits: Record<string, number>;
};
export type Revision = {
  id: string;
  state: string;
  created_at: number;
  manifest: Job["result"];
};
let csrf = "";
export class RagApiError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
  ) {
    super(message);
    this.name = "RagApiError";
  }
}
export function setCsrf(value: string) {
  csrf = value;
}
export function belongsTo(
  workspaceId: string,
  result: { workspace_id: string },
) {
  return result.workspace_id === workspaceId;
}
export function locationLabel(e: Evidence) {
  const l = e.location;
  return l.type === "text"
    ? `줄 ${l.start_line}–${l.end_line}`
    : `${l.sheet} · ${l.cell_range}`;
}
export const labels: Record<string, string> = {
  READY: "등록됨",
  REGISTERED: "문서 등록 전",
  QUEUED: "대기 중",
  RUNNING: "문서 등록 중",
  SCANNING: "문서 등록 중",
  BUILDING: "문서 등록 중",
  VALIDATING: "문서 등록 중",
  PARTIAL: "일부 파일 확인 필요",
  FAILED: "실패",
  CANCELLED: "취소됨",
  PROCESSED: "등록됨",
  REVIEWED: "확인 필요",
  PROCESSED_WITH_WARNINGS: "확인 필요",
  INCLUDED: "등록 가능",
  EXCLUDED: "제외",
  NOT_READY: "이용 준비 중",
  LOADING: "이용 준비 중",
  DOWNLOADING: "이용 준비 중",
};
export const reasons: Record<string, string> = {
  EXTERNAL_LLM_NOT_APPROVED:
    "이 워크스페이스의 질문 기능을 준비해 주세요. 문서 검색은 계속 이용할 수 있습니다.",
  LLM_POLICY_NOT_READY:
    "질문 기능을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.",
  PROXY_NOT_CONFIGURED:
    "질문 기능을 준비하고 있습니다. 관리자에게 문의해 주세요.",
  PROXY_MODEL_OR_OPTIONS_INVALID:
    "현재 답변을 생성할 수 없습니다. 문제가 계속되면 관리자에게 문의해 주세요.",
  PROXY_AUTH_FAILED: "서비스 연결을 확인해야 합니다. 관리자에게 문의해 주세요.",
  PROXY_RATE_LIMIT:
    "이용량이 많아 답변이 지연되고 있습니다. 잠시 후 다시 질문해 주세요.",
  PROXY_UNAVAILABLE:
    "답변 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  PROXY_TIMEOUT:
    "답변에 시간이 걸리고 있습니다. 질문의 범위를 좁히거나 다시 시도해 주세요.",
  LLM_BUSY: "다른 질문을 확인하고 있습니다. 잠시 후 다시 시도해 주세요.",
  SETTINGS_CHANGED: "서비스 설정이 갱신되었습니다. 다시 시도해 주세요.",
  UNSUPPORTED_FORMAT: "지원하지 않는 형식",
  POLICY_EXCLUDED: "보호 대상·숨김·임시 파일",
  SYMLINK_EXCLUDED: "바로가기 파일은 제외됩니다",
  SPECIAL_FILE: "일반 파일 아님",
  HARDLINK_EXCLUDED: "연결된 사본은 제외됩니다",
  FILE_SIZE_LIMIT: "파일 크기 제한 초과",
  DECODE_ERROR: "글자를 읽을 수 없습니다. 파일을 다시 저장해 주세요.",
  TABLE_HEADER_REVIEW_REQUIRED: "표의 첫 행에 각 열의 이름을 적어 주세요.",
  TABLE_BOUNDARY_REVIEW_REQUIRED: "여러 표의 경계 확인 필요",
  TABLE_WIDTH_REVIEW_REQUIRED: "표의 열 수 확인 필요",
  SOURCE_UNAVAILABLE: "폴더 권한·연결 확인 필요",
  MODEL_NOT_READY: "문서 검색 준비 중",
  NO_SEARCHABLE_CONTENT: "검색 가능한 내용 없음",
  SERVER_RESTARTED: "서비스 재연결 · 다시 시도해 주세요",
};
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
  signal?: AbortSignal,
  headers?: Record<string, string>,
): Promise<T> {
  const response = await fetch("/api/rag" + path, {
    method: method ?? (body === undefined ? "GET" : "POST"),
    credentials: "same-origin",
    signal,
    headers: {
      ...accessHeaders(),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      ...headers,
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw new RagApiError(
      reasons[data.error_code] ||
        (data.detail === "RAG_UNAVAILABLE"
          ? "문서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요."
          : "") ||
        (typeof data.message === "string" && /[가-힣]/.test(data.message)
          ? data.message
          : "") ||
        "요청을 처리하지 못했습니다.",
      data.error_code || "REQUEST_FAILED",
      response.status,
    );
  return data;
}

export function uploadFile(
  path: string,
  file: File,
  signal: AbortSignal,
  progress: (bytes: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const abortError = () =>
      new DOMException("업로드를 취소했습니다.", "AbortError");
    if (signal.aborted) return reject(abortError());
    const abort = () => xhr.abort();
    const cleanup = () => signal.removeEventListener("abort", abort);
    xhr.open("PUT", "/api/rag" + path);
    Object.entries({
      ...accessHeaders(),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    }).forEach(([key, value]) => xhr.setRequestHeader(key, value));
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.timeout = 150000;
    xhr.upload.onprogress = (event) =>
      progress(Math.min(file.size, event.loaded));
    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) return resolve();
      let message = "파일을 전송하지 못했습니다. 재시도하세요.";
      try {
        message = JSON.parse(xhr.responseText).message || message;
      } catch {
        /* No JSON on disconnect. */
      }
      reject(new Error(message));
    };
    xhr.onerror = xhr.ontimeout = () => {
      cleanup();
      reject(
        new Error("연결이 중단되었습니다. 연결 상태를 확인하고 재시도하세요."),
      );
    };
    xhr.onabort = () => {
      cleanup();
      reject(abortError());
    };
    signal.addEventListener("abort", abort, { once: true });
    xhr.send(file);
  });
}
