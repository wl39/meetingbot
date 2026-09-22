import { Sparkles } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import { codes, dates } from "./format";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function ConnectionCheck({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    "busy" | "dirty" | "cfg" | "checkConnection" | "check"
  >;
}) {
  const { busy, dirty, cfg, checkConnection, check } = settings;
  return (
    <section className="rag-panel rag-ai-section">
      <SectionHeading
        className="rag-ai-section-title"
        title="실제 답변으로 연결 확인"
        description="예시 문장을 전송해 답변이 정상적으로 생성되는지 확인합니다."
      >
        <button
          className="rag-secondary"
          disabled={
            !!busy || dirty || !cfg.default_model || !cfg.api_key_present
          }
          onClick={checkConnection}
        >
          <Sparkles size={16} />
          연결 확인
        </button>
      </SectionHeading>
      {check && (
        <div className="rag-ai-check">
          <strong>
            {check.completion_ok && check.json_ok
              ? "답변 생성 확인됨"
              : "연결 확인 필요"}
          </strong>
          <p>
            {check.model} · {dates(check.checked_at)}
          </p>
          <div className="rag-ai-check-items">
            <span>모델 목록 {check.models_ok ? "✓" : "—"}</span>
            <span>실제 응답 {check.completion_ok ? "✓" : "—"}</span>
            <span>응답 형식 {check.json_ok ? "✓" : "—"}</span>
          </div>
          {check.error_code && (
            <p role="alert">{codes[check.error_code] || check.error_code}</p>
          )}
        </div>
      )}
    </section>
  );
}
