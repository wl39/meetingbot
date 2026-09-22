import { Download, Layers3, Loader2 } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import type { Embedding } from "../hooks/useRetrievalSettings";

type EmbeddingCardProps = {
  embedding: Embedding | null;
  embeddingBusy: boolean;
  busy: string;
  onPrepare: () => Promise<void>;
};

export default function EmbeddingCard({
  embedding,
  embeddingBusy,
  busy,
  onPrepare,
}: EmbeddingCardProps) {
  return (
    <section className="management-card">
      <SectionHeading
        className="management-card-heading"
        icon={<Layers3 size={21} />}
        title="자료 검색 모델"
        description="문서의 의미를 읽어 검색에 사용하는 로컬 임베딩 모델입니다."
      >
        <span
          className={`management-badge ${embedding?.state === "READY" ? "good" : ""}`}
        >
          {embedding?.state === "READY"
            ? "준비 완료"
            : embeddingBusy
              ? "준비 중"
              : "준비 필요"}
        </span>
      </SectionHeading>
      <div className="management-inline-action">
        <p className="management-muted">
          {embedding?.model || "설정된 임베딩 모델"}
          <br />첫 준비에는 인터넷 연결과 모델 저장 공간이 필요합니다.
        </p>
        <button
          className="management-secondary"
          disabled={!!busy || !!embeddingBusy || embedding?.state === "READY"}
          onClick={() => void onPrepare()}
        >
          {embeddingBusy ? (
            <Loader2 size={18} className="management-spin" />
          ) : (
            <Download size={18} />
          )}
          {embedding?.state === "READY" ? "준비 완료" : "검색 모델 준비"}
        </button>
      </div>
    </section>
  );
}
