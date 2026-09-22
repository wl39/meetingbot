import { CheckCircle2 } from "lucide-react";
import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import EmbeddingCard from "./components/EmbeddingCard";
import ReindexCard from "./components/ReindexCard";
import RetrievalSettingsForm from "./components/RetrievalSettingsForm";
import { useRetrievalSettings } from "./hooks/useRetrievalSettings";

export default function RetrievalSection({ active }: { active: boolean }) {
  const settings = useRetrievalSettings(active);
  const { config, draft, embedding, error, notice } = settings;
  return (
    <>
      {error && (
        <FeedbackMessage
          className="management-error"
          tone="error"
          onDismiss={settings.clearError}
          dismissLabel="자료 설정 오류 닫기"
        >
          <span>{error}</span>
        </FeedbackMessage>
      )}
      {notice && !embedding?.error_code && (
        <FeedbackMessage
          className="management-notice"
          icon={<CheckCircle2 size={18} />}
        >
          {notice}
        </FeedbackMessage>
      )}
      {embedding?.error_code && (
        <FeedbackMessage className="management-error" tone="error">
          검색 모델 준비에 실패했습니다. 연결과 저장 공간을 확인한 뒤 ‘검색 모델
          준비’를 다시 눌러 주세요.
        </FeedbackMessage>
      )}
      <EmbeddingCard
        embedding={embedding}
        embeddingBusy={settings.embeddingBusy}
        busy={settings.busy}
        onPrepare={settings.prepareEmbedding}
      />
      {!draft || !config ? (
        <div className="management-empty" role="status">
          자료 검색 설정을 불러오는 중…
        </div>
      ) : (
        <>
          <RetrievalSettingsForm
            config={config}
            draft={draft}
            busy={settings.busy}
            valid={settings.valid}
            dirty={settings.dirty}
            setDraft={settings.setDraft}
            onSave={settings.save}
            onReset={settings.reset}
          />
          <ReindexCard
            config={config}
            indexJobs={settings.indexJobs}
            busy={settings.busy}
            dirty={settings.dirty}
            embeddingReady={embedding?.state === "READY"}
            onReindex={settings.reindex}
          />
        </>
      )}
    </>
  );
}
