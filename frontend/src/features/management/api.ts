import { token } from "../stt/api";
import { api as ragApi, setCsrf } from "../rag/api";

export type EngineId = "mlx" | "faster-whisper";
export type ModelId = "small" | "large-v3-turbo";
export type InstallJob = {
  id: string;
  action: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  message: string;
  progress: number | null;
  created_at: string;
  finished_at: string | null;
  error?: string | null;
};
export type SystemStatus = {
  platform: { os: string; machine: string; python: string };
  selection: { engine: EngineId; model: ModelId };
  engines: {
    id: EngineId;
    name: string;
    supported: boolean;
    installed: boolean;
    reason?: string | null;
  }[];
  models: {
    id: string;
    engine: EngineId;
    model: ModelId;
    name: string;
    installed: boolean;
    supported: boolean;
    download_gb: number;
  }[];
  workers: Record<
    string,
    {
      ready?: boolean;
      state?: string;
      error?: string;
      models?: Record<string, { ready?: boolean }>;
    }
  >;
  active_session: string | null;
  busy: boolean;
  jobs: InstallJob[];
  updates: { supported: boolean; reason: string };
  storage: { free_bytes: number };
  access?: {
    local_url: string;
    remote_url: string | null;
    kind: "tailscale" | "custom" | null;
  };
};
export type RagSettings = {
  version: number;
  chunk_tokens: number;
  overlap_tokens: number;
  top_k: number;
  updated_at: number | null;
  limits: Record<
    "chunk_tokens" | "overlap_tokens" | "top_k",
    { min: number; max: number }
  >;
  reindex_required: boolean;
  workspaces: {
    workspace_id: string;
    name: string;
    active_revision_id: string | null;
    chunk_count: number;
    requires_reindex: boolean;
    has_source: boolean;
    indexing: boolean;
  }[];
};

const errors: Record<string, string> = {
  LOCAL_AUTH_REQUIRED: "접속 키를 확인하고 다시 로그인해 주세요.",
  MANAGEMENT_BUSY: "다른 설치나 전사가 진행 중입니다. 완료 후 다시 시도하세요.",
  TRANSCRIPTION_ACTIVE: "진행 중인 전사를 완료한 뒤 모델을 적용해 주세요.",
  WORKERS_LOADING: "음성 엔진을 불러오는 중입니다. 준비 후 다시 시도하세요.",
  MODEL_NOT_INSTALLED: "이 모델을 먼저 설치해 주세요.",
  ENGINE_UNSUPPORTED: "이 운영체제에서 사용할 수 없는 엔진입니다.",
  SETTINGS_VERSION_CONFLICT:
    "다른 화면에서 설정이 변경되었습니다. 최신 설정을 불러온 뒤 다시 저장하세요.",
};
export const errorMessage = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";

export async function systemApi<T>(path = "", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api/system" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: {
        Authorization: `Bearer ${token()}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "서버에 연결할 수 없습니다. 연결 상태를 확인하고 다시 시도하세요.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const code =
      typeof data.detail === "string" ? data.detail : data.error_code;
    throw new Error(
      errors[code] ||
        data.message ||
        (response.status === 404
          ? "서버에 관리 기능이 아직 반영되지 않았습니다. 업데이트된 서버에서 다시 열어 주세요."
          : "요청을 처리하지 못했습니다. 잠시 후 다시 시도하세요."),
    );
  }
  return data;
}

// Settings also work when opened directly, before the library has established a session.
export async function connectRag(credential: string) {
  let result: { csrf: string };
  try {
    result = await ragApi<{ csrf: string }>("/auth/session");
  } catch {
    result = await ragApi<{ csrf: string }>("/auth/login", { key: credential });
  }
  setCsrf(result.csrf);
}
