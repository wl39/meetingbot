export const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "요청을 처리하지 못했습니다.";
export const dates = (n: number) => new Date(n * 1000).toLocaleString("ko-KR");
export const codes: Record<string, string> = {
  PROXY_NO_MODELS: "연결된 모델이 없습니다. Codex 계정 로그인을 완료하세요.",
  PROXY_AUTH_FAILED: "연결 키 또는 Codex 로그인을 확인하세요.",
  PROXY_RATE_LIMIT: "모델 사용 한도에 도달했습니다. 잠시 후 다시 시도하세요.",
  PROXY_TIMEOUT: "응답 시간이 초과됐습니다. 제한 시간을 늘려 보세요.",
  PROXY_MODEL_OR_OPTIONS_INVALID:
    "이 모델에서 지원하는 모델 ID와 옵션을 확인하세요.",
  PROXY_NOT_CONFIGURED: "연결 키와 기본 모델을 먼저 설정하세요.",
  PROXY_UNAVAILABLE: "AI 서비스 연결을 확인하세요.",
};
