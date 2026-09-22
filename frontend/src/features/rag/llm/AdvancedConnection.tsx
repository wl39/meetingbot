import { SectionHeading } from "../../../components/ui/SectionHeading";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function AdvancedConnection({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    | "busy"
    | "codex"
    | "useDefaultConnection"
    | "cfg"
    | "setCfg"
    | "key"
    | "setKey"
    | "clearKey"
    | "setClearKey"
    | "saved"
  >;
}) {
  const {
    busy,
    codex,
    useDefaultConnection,
    cfg,
    setCfg,
    key,
    setKey,
    clearKey,
    setClearKey,
    saved,
  } = settings;
  return (
    <details className="rag-panel rag-ai-section rag-connection-details">
      <summary>고급 연결 설정</summary>
      <SectionHeading className="rag-ai-section-title" title="사용자 지정 연결">
        <button
          type="button"
          className="rag-secondary"
          disabled={!!busy || !codex?.installed}
          onClick={useDefaultConnection}
        >
          기본 연결 사용
        </button>
      </SectionHeading>
      <div className="rag-ai-fields">
        <label>
          API 주소
          <input
            type="url"
            required
            value={cfg.base_url}
            onInvalid={(event) =>
              event.currentTarget.closest("details")?.setAttribute("open", "")
            }
            onChange={(e) => setCfg({ ...cfg, base_url: e.target.value })}
          />
          <small>OpenAI 호환 API 주소를 입력하세요.</small>
        </label>
        <label>
          연결 키
          <input
            type="password"
            autoComplete="new-password"
            value={key}
            placeholder={
              cfg.api_key_present
                ? "저장된 키 있음 · 변경할 때만 입력"
                : "연결 키를 입력하세요"
            }
            onChange={(e) => setKey(e.target.value)}
          />
          <small>저장된 키는 화면에 다시 표시하지 않습니다.</small>
        </label>
      </div>
      <label className="rag-ai-checkbox">
        <input
          type="checkbox"
          checked={clearKey}
          onChange={(e) => setClearKey(e.target.checked)}
        />
        저장 시 연결 키 지우기
      </label>
      {cfg.base_url !== saved?.base_url && (
        <p className="rag-ai-hint">
          주소를 변경하면 기존 키는 지워집니다. 새 연결 키도 입력하세요.
        </p>
      )}
    </details>
  );
}
