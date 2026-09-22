import { Check, Loader2, SlidersHorizontal } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import type { RagSettings } from "../api";
import type { RagDraft } from "../hooks/useRetrievalSettings";

type RetrievalSettingsFormProps = {
  config: RagSettings;
  draft: RagDraft;
  busy: string;
  valid: boolean;
  dirty: boolean;
  setDraft: (draft: RagDraft) => void;
  onSave: () => Promise<void>;
  onReset: () => Promise<void>;
};

export default function RetrievalSettingsForm({
  config,
  draft,
  busy,
  valid,
  dirty,
  setDraft,
  onSave,
  onReset,
}: RetrievalSettingsFormProps) {
  return (
    <form
      className="management-card"
      onSubmit={(event) => {
        event.preventDefault();
        void onSave();
      }}
    >
      <SectionHeading
        className="management-card-heading"
        icon={<SlidersHorizontal size={21} />}
        title="문서를 나누고, 근거를 찾는 방식"
        description="청크는 검색을 위해 문서를 나눈 조각입니다."
      />
      <div
        className="management-presets"
        role="group"
        aria-label="청킹 추천 설정"
      >
        {[
          {
            label: "세밀하게",
            size: 128,
            overlap: 24,
            description: "짧은 구절 중심",
          },
          {
            label: "균형 있게",
            size: 256,
            overlap: 32,
            description: "일반적인 문서",
          },
          {
            label: "넓게 읽기",
            size: 384,
            overlap: 48,
            description: "긴 문맥 중심",
          },
        ].map((preset) => (
          <button
            type="button"
            key={preset.size}
            disabled={!!busy}
            aria-pressed={
              draft.chunk_tokens === preset.size &&
              draft.overlap_tokens === preset.overlap
            }
            onClick={() =>
              setDraft({
                ...draft,
                chunk_tokens: preset.size,
                overlap_tokens: preset.overlap,
              })
            }
          >
            <strong>{preset.label}</strong>
            <small>{preset.description}</small>
          </button>
        ))}
      </div>
      <div className="management-rag-fields">
        <label htmlFor="chunk-size">
          <span>
            청크 크기 <small>토큰</small>
          </span>
          <input
            id="chunk-size"
            type="number"
            min={config.limits.chunk_tokens.min}
            max={config.limits.chunk_tokens.max}
            required
            disabled={!!busy}
            value={draft.chunk_tokens}
            onChange={(event) =>
              setDraft({
                ...draft,
                chunk_tokens: Number(event.target.value),
              })
            }
          />
          <small>
            작게 나눌수록 청크 수가 늘어나고, 크게 나눌수록 줄어듭니다.
          </small>
        </label>
        <label htmlFor="chunk-overlap">
          <span>
            겹치는 문맥 <small>토큰</small>
          </span>
          <input
            id="chunk-overlap"
            type="number"
            min={0}
            max={draft.chunk_tokens - 1}
            required
            disabled={!!busy}
            value={draft.overlap_tokens}
            onChange={(event) =>
              setDraft({
                ...draft,
                overlap_tokens: Number(event.target.value),
              })
            }
          />
          <small>
            조각 사이에서 이어 읽을 분량입니다. 청크 크기보다 작아야 합니다.
          </small>
        </label>
        <label htmlFor="retrieval-count">
          <span>
            검색 근거 개수 <small>개</small>
          </span>
          <input
            id="retrieval-count"
            type="number"
            min={config.limits.top_k.min}
            max={config.limits.top_k.max}
            required
            disabled={!!busy}
            value={draft.top_k}
            onChange={(event) =>
              setDraft({ ...draft, top_k: Number(event.target.value) })
            }
          />
          <small>
            질문에 참고할 근거의 최대 개수입니다. 실시간 도우미는 최대 6개를
            사용합니다.
          </small>
        </label>
      </div>
      {!valid && (
        <p className="management-field-error" role="alert">
          청크 크기는 {config.limits.chunk_tokens.min}~
          {config.limits.chunk_tokens.max}, 겹치는 문맥은 0~청크 크기 미만, 검색
          근거는 {config.limits.top_k.min}~{config.limits.top_k.max} 사이의
          정수로 입력하세요.
        </p>
      )}
      <div className="management-save-row">
        <span>
          {dirty ? "저장하지 않은 변경 내용이 있습니다." : "저장된 설정입니다."}
        </span>
        <button
          type="button"
          className="management-secondary"
          disabled={!!busy}
          onClick={() => void onReset()}
        >
          저장된 값 불러오기
        </button>
        <button
          className="management-primary"
          disabled={!!busy || !dirty || !valid}
        >
          {busy === "설정 저장 중" ? (
            <Loader2 size={17} className="management-spin" />
          ) : (
            <Check size={17} />
          )}
          설정 저장
        </button>
      </div>
    </form>
  );
}
