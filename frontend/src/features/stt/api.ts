import { accessHeaders } from "../../workspace/access";
export type Options = {
  model: "small" | "large-v3-turbo";
  language: "ko";
  num_speakers: number | null;
  retain_audio: boolean;
};
export type WordTiming = {
  text: string;
  start_ms: number;
  end_ms: number;
};
export type Utterance = {
  utterance_id: string;
  revision: number;
  start_ms: number;
  end_ms: number;
  text: string;
  words?: WordTiming[];
  speaker_id: string | null;
  status: string;
  speaker_status: string;
  overlap: boolean;
  manual_fields: string[];
};
export type Session = {
  source_file?: { name: string; size: number };
  id: string;
  snapshot_revision: number;
  mode: string;
  state: string;
  utterances: Utterance[];
  speakers: Record<string, string>;
  warnings: {
    type: string;
    code?: string;
    stage?: string;
    duration_seconds?: number;
    max_seconds?: number;
  }[];
  metrics: Record<string, number>;
  audio_retained: boolean;
};
export type Health = {
  default_model?: Options["model"];
  asr_backend?: "mlx" | "faster-whisper";
  management_busy?: boolean;
  limits: { file_mb: number; file_seconds: number; live_seconds: number };
  engine: string;
  active_session: string | null;
  workers: Record<
    string,
    {
      ready: boolean;
      state?: string;
      error?: string;
      models?: Record<string, { ready: boolean }>;
    }
  >;
  environment: { machine: string; system: string };
};
export function modelReady(
  health: Health | null,
  model: Options["model"],
): boolean {
  const worker = health?.workers.asr;
  if (!worker?.ready || health?.management_busy) return false;
  return worker.models ? worker.models[model]?.ready === true : true;
}
export function warningMessage(w: Session["warnings"][number]): string {
  if (w.type === "file.failed") {
    if (w.code === "AUDIO_TOO_LONG") {
      const limit = w.max_seconds ?? 18000;
      const duration = w.duration_seconds;
      return `파일 길이가 최대 ${limit / 60}분을 초과했습니다.${duration ? ` 감지된 길이: ${Math.floor(duration / 60)}분 ${Math.ceil(duration % 60)}초.` : ""} 파일을 나눠 올려 주세요.`;
    }
    const messages: Record<string, string> = {
      AUDIO_PROBE_FAILED:
        "오디오 파일을 읽을 수 없습니다. 기기에서 정상 재생되는지 확인하고 M4A 또는 WAV로 다시 내보내 주세요.",
      AUDIO_DECODE_FAILED:
        "오디오 변환에 실패했습니다. M4A 또는 WAV로 다시 내보내 주세요.",
      NO_AUDIO_STREAM: "파일에 오디오 트랙이 없습니다.",
      INVALID_DECODED_AUDIO: "파일에서 유효한 오디오를 읽지 못했습니다.",
      AUDIO_DECODE_TIMEOUT:
        "오디오 변환 시간이 초과됐습니다. 파일을 나눠 다시 시도해 주세요.",
      AUDIO_TOOL_MISSING:
        "음성 파일을 처리할 수 없습니다. 관리자에게 문의해 주세요.",
      UPLOAD_INTERRUPTED:
        "파일 전송이 중단되었습니다. 연결을 확인하고 다시 올려 주세요.",
      UPLOAD_CANCELLED: "파일 전송이 취소되었습니다.",
    };
    return (
      messages[w.code ?? ""] ??
      "파일을 처리하지 못했습니다. 파일을 확인한 뒤 다시 시도해 주세요."
    );
  }
  return (
    (
      {
        "diarization.failed":
          "발언자를 구분하지 못했습니다. 대본에서 이름을 직접 지정할 수 있습니다.",
        "audio.gap": "오디오 누락이 감지되었습니다.",
        "stream.interrupted": "입력 연결이 중단되었습니다.",
        "asr.failed": "음성 인식 중 오류가 발생했습니다.",
        "service.restarted":
          "서비스 재연결로 작업이 중단되었습니다. 다시 시도해 주세요.",
      } as Record<string, string>
    )[w.type] ??
    "기록의 일부를 확인해야 합니다. 음성과 대본을 함께 확인해 주세요."
  );
}
/** Keep technical error codes available to callers, but never show them in the UI. */
export function errorMessage(error: unknown): string {
  const message = String(
    error instanceof Error ? error.message : error,
  ).replace(/^(?:Error|TypeError|DOMException):\s*/, "");
  const messages: Record<string, string> = {
    LOCAL_AUTH_REQUIRED: "로그인이 필요합니다. 다시 접속해 주세요.",
    NOT_FOUND: "기록을 찾을 수 없습니다. 최근 기록에서 다시 선택해 주세요.",
    REVISION_CONFLICT:
      "대본이 업데이트되었습니다. 최신 내용을 확인한 뒤 다시 수정해 주세요.",
    MODEL_NOT_READY:
      "음성 기록을 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    ASR_NOT_READY:
      "음성 기록을 잠시 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.",
    UPLOAD_NOT_FOUND: "파일 전송이 중단되었습니다. 파일을 다시 올려 주세요.",
    BUSY: "다른 음성을 정리하고 있습니다. 잠시 후 다시 시도해 주세요.",
  };
  if (messages[message]) return messages[message];
  // All deliberate product messages are localized; unknown failures may include
  // transport details or backend tracebacks and get a safe actionable fallback.
  return /[가-힣]/.test(message) &&
    !/Traceback|Exception|\bat \w|\{/.test(message)
    ? message
    : "요청을 완료하지 못했습니다. 연결을 확인하고 다시 시도해 주세요.";
}
export const token = () => sessionStorage.getItem("stt-token") || "";
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch("/api/stt" + path, {
    ...init,
    headers: {
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...accessHeaders(),
      ...init.headers,
    },
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      message = (await response.json()).detail || message;
    } catch {
      /* Non-JSON proxy errors. */
    }
    throw new Error(
      (
        {
          DEMO_DAILY_LIMIT:
            "오늘의 데모 전사 사용 한도에 도달했습니다. 내일 다시 체험해 주세요.",
          BUSY: "다른 전사를 처리 중입니다. 잠시 후 다시 시도해 주세요.",
          ROLE_DENIED: "이 기능을 사용할 권한이 없습니다.",
          FILE_TOO_LARGE: "데모에서는 20MB 이하 파일을 사용해 주세요.",
        } as Record<string, string>
      )[message] || message,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export type ExportFormat = "txt" | "srt" | "json";
export type TranscriptMode = "utterance" | "script";
export type ExportPreview = {
  content: string;
  total_items: number;
  preview_items: number;
};
export async function download(
  sid: string,
  format: ExportFormat,
  view: TranscriptMode = "utterance",
) {
  const response = await fetch(
    `/api/stt/sessions/${sid}/export?format=${format}&view=${view}`,
    { headers: accessHeaders() },
  );
  if (!response.ok) throw new Error("내보내기에 실패했습니다.");
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `transcript-${view}.${format}`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const defaults: Options = {
  model: "small",
  language: "ko",
  num_speakers: null,
  retain_audio: false,
};
export const terminal = (state: string) =>
  ["COMPLETED", "PARTIAL", "FAILED", "INTERRUPTED", "CANCELLED"].includes(
    state,
  );
export const time = (ms: number) =>
  `${String(Math.floor(ms / 60000)).padStart(2, "0")}:${((ms / 1000) % 60).toFixed(1).padStart(4, "0")}`;
export const states: Record<string, string> = {
  UPLOADING: "파일 전송 중",
  CREATED: "시작 대기",
  QUEUED: "대기 중",
  PREPROCESSING: "오디오 준비 중",
  TRANSCRIBING: "음성을 텍스트로 변환 중",
  DIARIZING: "발언자 정리 중",
  MERGING: "대본 정리 중",
  RECORDING: "녹음 중",
  FINALIZING: "대본 마무리 중",
  COMPLETED: "완료",
  PARTIAL: "부분 완료",
  FAILED: "처리 실패",
  INTERRUPTED: "연결 중단",
  CANCELLED: "취소됨",
};

export function latestSnapshot(
  current: Session | null,
  incoming: Session,
): Session {
  return current?.id === incoming.id &&
    current.snapshot_revision > incoming.snapshot_revision
    ? current
    : incoming;
}
