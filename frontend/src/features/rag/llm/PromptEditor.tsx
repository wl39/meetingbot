import { Save } from "lucide-react";
import type { ReadyLlmSettings } from "./useLlmSettings";

export default function PromptEditor({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    "editor" | "setEditor" | "setPreview" | "busy" | "run" | "savePrompt"
  >;
}) {
  const { editor, setEditor, setPreview, busy, run, savePrompt } = settings;
  return (
    <section className="rag-panel rag-ai-section">
      <h2>답변 작성 지침</h2>
      <p>
        자료 밖의 답변을 제한하고 숫자·표·상충 근거를 다루는 기본 지침이
        준비되어 있습니다. 답변 형식과 출처의 유효성은 자동으로 확인합니다.
      </p>
      <label>
        프롬프트 이름
        <input
          maxLength={100}
          value={editor.name}
          onChange={(e) => setEditor({ ...editor, name: e.target.value })}
        />
      </label>
      <label>
        답변 작성 지침
        <textarea
          className="rag-ai-editor"
          minLength={20}
          maxLength={12000}
          value={editor.content}
          onChange={(e) => {
            setEditor({ ...editor, content: e.target.value });
            setPreview(null);
          }}
        />
        <small>
          {editor.content.length.toLocaleString()} / 12,000자 · 편집 중인 기준 v
          {editor.sequence}
        </small>
      </label>
      <label>
        변경 메모
        <input
          maxLength={500}
          placeholder="어떤 점을 바꿨나요?"
          value={editor.note}
          onChange={(e) => setEditor({ ...editor, note: e.target.value })}
        />
      </label>
      <div className="rag-ai-actions">
        <button
          className="rag-secondary"
          disabled={
            !!busy || editor.content.trim().length < 20 || !editor.name.trim()
          }
          onClick={() => run("새 버전 저장 중…", () => savePrompt(false))}
        >
          <Save size={16} />새 버전 저장
        </button>
        <button
          className="rag-primary"
          disabled={
            !!busy || editor.content.trim().length < 20 || !editor.name.trim()
          }
          onClick={() => run("새 버전 적용 중…", () => savePrompt(true))}
        >
          저장하고 적용
        </button>
      </div>
    </section>
  );
}
