import { RefreshCw, Save } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function ModelOptions({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    | "busy"
    | "dirty"
    | "cfg"
    | "refreshModels"
    | "models"
    | "setCfg"
    | "setCheck"
  >;
}) {
  const { busy, dirty, cfg, refreshModels, models, setCfg, setCheck } =
    settings;
  return (
    <section className="rag-panel rag-ai-section">
      <SectionHeading
        className="rag-ai-section-title"
        title="기본 모델과 답변 옵션"
      >
        <button
          type="button"
          className="rag-secondary"
          disabled={!!busy || dirty || !cfg.api_key_present}
          onClick={refreshModels}
        >
          <RefreshCw size={15} />
          모델 목록 불러오기
        </button>
      </SectionHeading>
      <div className="rag-ai-fields">
        <label>
          기본 모델
          <select
            aria-label="기본 모델"
            required={cfg.enabled}
            disabled={!!busy}
            value={cfg.default_model}
            onChange={(e) => {
              setCfg({ ...cfg, default_model: e.target.value });
              setCheck(null);
            }}
          >
            <option value="" disabled>
              모델을 선택하세요
            </option>
            {cfg.default_model && !models.includes(cfg.default_model) && (
              <option value={cfg.default_model}>
                {cfg.default_model} (직접 입력)
              </option>
            )}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <small>
            {models.length
              ? `${models.length}개 모델 · 선택 후 설정을 저장하세요.`
              : "계정 연결 후 모델 목록을 불러오세요."}
          </small>
        </label>
        <label>
          최대 출력 토큰
          <input
            type="number"
            min={256}
            max={16384}
            required
            value={cfg.max_output_tokens}
            onChange={(e) =>
              setCfg({
                ...cfg,
                max_output_tokens: Number(e.target.value),
              })
            }
          />
          <small>길거나 복잡한 답변에 쓸 출력 한도</small>
        </label>
      </div>
      <details className="rag-ai-advanced">
        <summary>고급 답변 옵션</summary>
        <label>
          모델 ID 직접 입력
          <input
            aria-label="모델 ID 직접 입력"
            placeholder="목록에 없는 모델의 ID"
            value={cfg.default_model}
            disabled={!!busy}
            onChange={(e) => {
              setCfg({ ...cfg, default_model: e.target.value });
              setCheck(null);
            }}
          />
          <small>직접 입력한 모델도 위 선택창에 표시됩니다.</small>
        </label>
        <div className="rag-ai-fields">
          <label>
            응답 제한 시간 (초)
            <input
              type="number"
              min={10}
              max={180}
              required
              value={cfg.timeout_seconds}
              onChange={(e) =>
                setCfg({
                  ...cfg,
                  timeout_seconds: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            입력 문자 한도
            <input
              type="number"
              min={4000}
              max={64000}
              required
              value={cfg.input_chars}
              onChange={(e) =>
                setCfg({ ...cfg, input_chars: Number(e.target.value) })
              }
            />
          </label>
          <label>
            추론 강도
            <select
              value={cfg.reasoning_effort ?? ""}
              onChange={(e) =>
                setCfg({
                  ...cfg,
                  reasoning_effort: e.target.value || null,
                })
              }
            >
              <option value="">모델 기본값</option>
              {["none", "minimal", "low", "medium", "high", "xhigh"].map(
                (x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            Temperature
            <input
              type="number"
              min={0}
              max={2}
              step={0.1}
              placeholder="모델 기본값"
              value={cfg.temperature ?? ""}
              onChange={(e) =>
                setCfg({
                  ...cfg,
                  temperature:
                    e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </label>
        </div>
        <p>
          모델마다 지원하는 옵션이 다릅니다. 기본값은 옵션을 별도로 지정하지
          않습니다.
        </p>
      </details>
      <label className="rag-ai-toggle">
        <input
          type="checkbox"
          checked={cfg.enabled}
          onChange={(e) => setCfg({ ...cfg, enabled: e.target.checked })}
        />
        <span>
          <strong>AI 답변 사용</strong>
          <small>
            각 워크스페이스 설정에서 질문·근거 전송을 승인하면 답변이
            생성됩니다.
          </small>
        </span>
      </label>
      <div className="rag-ai-save">
        <span>
          {dirty
            ? "저장하지 않은 변경 내용이 있습니다."
            : "모든 변경 내용이 저장되었습니다."}
        </span>
        <button className="rag-primary" disabled={!!busy || !dirty}>
          <Save size={16} />
          설정 저장
        </button>
      </div>
    </section>
  );
}
