import { AudioLines, Check, Download } from "lucide-react";
import type { SystemStatus } from "./api";
import { engineName, modelName } from "./format";
import { SectionHeading } from "../../components/ui/SectionHeading";
import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import JobList from "./components/JobList";
export default function SpeechSection({
  status,
  pending,
  execute,
}: {
  status: SystemStatus | null;
  pending: boolean;
  execute: (path: string, body: unknown) => Promise<void>;
}) {
  if (!status)
    return (
      <div className="management-empty">
        서버에 연결하면 설치 가능한 음성 모델을 확인할 수 있습니다.
      </div>
    );
  const blocked = pending || status.busy || !!status.active_session;
  return (
    <>
      <div className="management-info">
        <AudioLines size={20} />
        <div>
          <strong>
            현재 설정: {engineName(status.selection.engine)} ·{" "}
            {modelName(status.selection.model)}
          </strong>
          <p>
            설치 후 ‘이 모델 사용’을 누르면 다음 전사부터 적용됩니다. 진행 중인
            전사가 있으면 완료 후 변경할 수 있습니다.
          </p>
        </div>
      </div>
      {status.active_session && (
        <FeedbackMessage className="management-notice">
          전사가 진행 중입니다. 작업이 끝나면 설치와 모델 변경을 할 수 있습니다.
        </FeedbackMessage>
      )}
      {status.engines.map((engine) => (
        <section className="management-card" key={engine.id}>
          <SectionHeading
            className="management-card-heading"
            icon={<AudioLines size={22} />}
            title={engine.name}
            description={
              <>
                {engine.id === "mlx"
                  ? "Apple Silicon Mac에 맞춘 음성 인식"
                  : "Windows · macOS · Linux에서 사용하는 CPU 음성 인식"}
              </>
            }
          >
            <span
              className={`management-badge ${engine.supported ? "good" : ""}`}
            >
              {!engine.supported
                ? "현재 환경 미지원"
                : engine.installed
                  ? "엔진 설치됨"
                  : "설치 가능"}
            </span>
          </SectionHeading>
          {!engine.supported && (
            <p className="management-muted">
              {engine.reason ||
                "이 서버의 운영체제나 프로세서에서 지원하지 않습니다."}
            </p>
          )}
          <div className="management-models">
            {status.models
              .filter((model) => model.engine === engine.id)
              .map((model) => {
                const selected =
                  status.selection.engine === model.engine &&
                  status.selection.model === model.model;
                const usable = model.installed && engine.installed;
                const ready =
                  selected &&
                  !!status.workers.asr?.ready &&
                  (status.workers.asr.models
                    ? !!status.workers.asr.models[model.model]?.ready
                    : true);
                return (
                  <div
                    className={`management-model ${selected ? "selected" : ""}`}
                    key={model.id}
                  >
                    <span className="management-model-glyph">
                      <AudioLines size={25} />
                    </span>
                    <div className="management-model-description">
                      <h3>
                        {modelName(model.model)}{" "}
                        {selected && (
                          <span
                            className={`management-badge ${ready ? "good" : ""}`}
                          >
                            {ready ? "사용 중" : "선택됨 · 준비 필요"}
                          </span>
                        )}
                      </h3>
                      <p>
                        {model.model === "small"
                          ? "가볍게 시작하는 일상 회의 기록"
                          : "정확도를 우선하는 긴 회의와 복잡한 대화"}
                      </p>
                      <small>
                        {model.installed
                          ? "모델 다운로드 완료"
                          : `모델 다운로드 약 ${model.download_gb} GB · 엔진 용량 별도`}
                      </small>
                    </div>
                    <button
                      className={
                        usable ? "management-secondary" : "management-primary"
                      }
                      disabled={blocked || !model.supported || ready}
                      onClick={() =>
                        void execute(usable ? "/selection" : "/install", {
                          engine: model.engine,
                          model: model.model,
                        })
                      }
                    >
                      {usable ? (
                        ready ? (
                          <>
                            <Check size={17} />
                            사용 중
                          </>
                        ) : (
                          "이 모델 사용"
                        )
                      ) : (
                        <>
                          <Download size={17} />
                          설치하기
                        </>
                      )}
                    </button>
                  </div>
                );
              })}
          </div>
        </section>
      ))}
      <section className="management-card">
        <SectionHeading
          className="management-card-heading"
          icon={<Download size={21} />}
          title="설치와 적용 상태"
          description="화면을 이동해도 서버에서 작업을 계속합니다."
        />
        <JobList jobs={status.jobs} />
      </section>
    </>
  );
}
