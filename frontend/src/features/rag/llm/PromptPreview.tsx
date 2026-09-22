import { Sparkles } from "lucide-react";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function PromptPreview({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    | "sample"
    | "setSample"
    | "setPreview"
    | "busy"
    | "editor"
    | "saved"
    | "previewPrompt"
    | "testPrompt"
    | "preview"
  >;
}) {
  const {
    sample,
    setSample,
    setPreview,
    busy,
    editor,
    saved,
    previewPrompt,
    testPrompt,
    preview,
  } = settings;
  return (
    <section className="rag-panel rag-ai-section">
      <h2>적용 전에 예시로 확인</h2>
      <p>
        편집 중인 프롬프트를 사용합니다. 미리보기에는 예시 자료만 AI로
        전송합니다.
      </p>
      <label>
        예시 상황
        <select
          value={sample}
          onChange={(e) => {
            setSample(e.target.value);
            setPreview(null);
          }}
        >
          <option value="supported">근거가 있는 질문</option>
          <option value="related">유사·관련 자료만 있는 질문</option>
          <option value="missing">자료에 없는 질문</option>
          <option value="conflict">자료끼리 충돌하는 질문</option>
          <option value="injection">문서에 악성 지시가 포함된 질문</option>
        </select>
      </label>
      <div className="rag-ai-actions">
        <button
          className="rag-secondary"
          disabled={!!busy || editor.content.trim().length < 20}
          onClick={previewPrompt}
        >
          입력 미리보기
        </button>
        <button
          className="rag-primary"
          disabled={
            !!busy ||
            !saved?.default_model ||
            !saved?.api_key_present ||
            editor.content.trim().length < 20
          }
          onClick={testPrompt}
        >
          <Sparkles size={16} />
          예시 답변 생성
        </button>
      </div>
      {preview && (
        <div className="rag-ai-preview">
          {preview.result && (
            <>
              <small>
                {preview.model} ·{" "}
                {((preview.elapsed_ms ?? 0) / 1000).toFixed(1)}초
              </small>
              <p className="rag-ai-output">{preview.result.answer}</p>
              <small>
                {{
                  answered: "근거 기반 답변",
                  related_evidence: "관련 자료 기반 안내",
                  insufficient_evidence: "근거 부족",
                  conflicting_evidence: "상충 근거",
                }[preview.result.status] || preview.result.status}{" "}
                · 인용 {preview.result.citations.join(", ") || "없음"}
              </small>
            </>
          )}
          <details open={!preview.result}>
            <summary>모델에 전달하는 입력</summary>
            {preview.messages.map((m) => (
              <div key={m.role}>
                <strong>
                  {m.role === "system" ? "답변 지침" : "예시 질문과 근거"}
                </strong>
                <pre>{m.content}</pre>
              </div>
            ))}
          </details>
        </div>
      )}
    </section>
  );
}
