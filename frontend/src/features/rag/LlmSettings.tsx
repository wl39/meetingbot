import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import {
  ArrowLeft,
  Check,
  History,
  Loader2,
  Settings2,
  Sparkles,
} from "lucide-react";
import "./llm.css";
import { useLlmSettings } from "./llm/useLlmSettings";
import AccountConnection from "./llm/AccountConnection";
import AdvancedConnection from "./llm/AdvancedConnection";
import ModelOptions from "./llm/ModelOptions";
import ConnectionCheck from "./llm/ConnectionCheck";
import PromptEditor from "./llm/PromptEditor";
import PromptPreview from "./llm/PromptPreview";
import PromptHistory from "./llm/PromptHistory";

export default function LlmSettings({ onBack }: { onBack: () => void }) {
  const settings = useLlmSettings();
  const {
    tab,
    setTab,
    cfg,
    editor,
    listing,
    codex,
    error,
    setError,
    notice,
    busy,
    run,
    save,
  } = settings;
  const readySettings =
    cfg && editor && listing ? { ...settings, cfg, editor, listing } : null;
  return (
    <div className="rag-ai">
      <button className="rag-back" onClick={onBack}>
        <ArrowLeft size={16} /> 라이브러리로
      </button>
      <div className="rag-title-row">
        <div>
          <h1>AI 설정</h1>
          <p>사용할 AI 모델과 답변 작성 지침을 관리하세요.</p>
        </div>
        <div className="rag-ai-badge">
          <Sparkles size={19} />
          {codex?.connected ? "Codex 연결됨" : "Codex 연결 준비"}
        </div>
      </div>
      <nav className="rag-ai-tabs" aria-label="AI 설정 메뉴">
        <button
          className={tab === "connection" ? "selected" : ""}
          onClick={() => setTab("connection")}
        >
          <Settings2 size={17} />
          연결 · 기본 모델
        </button>
        <button
          className={tab === "prompt" ? "selected" : ""}
          onClick={() => setTab("prompt")}
        >
          <History size={17} />
          프롬프트 관리
        </button>
      </nav>
      {error && (
        <FeedbackMessage
          tone="error"
          className="rag-alert"
          onDismiss={() => setError("")}
          dismissLabel="닫기"
          dismissContent="닫기"
        >
          {error}
        </FeedbackMessage>
      )}
      {notice && (
        <FeedbackMessage className="rag-ai-notice" icon={<Check size={17} />}>
          {notice}
        </FeedbackMessage>
      )}
      {busy && (
        <FeedbackMessage
          className="rag-ai-working"
          icon={<Loader2 size={16} className="rag-spin" />}
        >
          {busy}
        </FeedbackMessage>
      )}
      {!readySettings ? (
        <p>설정을 불러오는 중…</p>
      ) : tab === "connection" ? (
        <>
          <AccountConnection settings={readySettings} />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run("설정 저장 중…", save);
            }}
          >
            <AdvancedConnection settings={readySettings} />
            <ModelOptions settings={readySettings} />
          </form>
          <ConnectionCheck settings={readySettings} />
        </>
      ) : (
        <div className="rag-ai-prompt-grid">
          <div>
            <PromptEditor settings={readySettings} />
            <PromptPreview settings={readySettings} />
          </div>
          <PromptHistory settings={readySettings} />
        </div>
      )}
    </div>
  );
}
