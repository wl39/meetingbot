import {
  ArrowRight,
  AudioLines,
  Check,
  CheckCircle2,
  ChevronRight,
  HardDrive,
  SlidersHorizontal,
} from "lucide-react";
import type { SettingsPath } from "../../workspace/navigation";
import type { SystemStatus } from "./api";
import { bytes, engineName, modelName } from "./format";
import { SectionHeading } from "../../components/ui/SectionHeading";
import Preferences from "./components/Preferences";
import ThemeSettings from "./components/ThemeSettings";
export default function OverviewSection({
  status,
  navigate,
}: {
  status: SystemStatus | null;
  navigate: (path: SettingsPath) => void;
}) {
  return (
    <>
      <section className="management-welcome">
        <span className="management-welcome-icon">
          <SlidersHorizontal size={28} />
        </span>
        <div>
          <span className="management-kicker">내 환경에 맞게</span>
          <h2>
            회의에 집중하세요.
            <br />
            도구는 여기서 관리할게요.
          </h2>
          <p>
            음성 인식부터 자료 검색, AI 답변까지.
            <br className="management-mobile-break" /> 필요한 설정을 한곳에서
            조정하세요.
          </p>
        </div>
      </section>
      <div className="management-summary-grid">
        <button onClick={() => navigate("/settings/speech")}>
          <AudioLines size={22} />
          <span>
            <small>사용 중인 음성 모델</small>
            <strong>
              {status ? modelName(status.selection.model) : "설치 상태 확인 중"}
            </strong>
            <small>
              {status
                ? engineName(status.selection.engine)
                : "서버 연결이 필요합니다"}
            </small>
          </span>
          <ChevronRight size={18} />
        </button>
        <button onClick={() => navigate("/settings/updates")}>
          <HardDrive size={22} />
          <span>
            <small>서버 저장 공간</small>
            <strong>
              {status ? `${bytes(status.storage.free_bytes)} 여유` : "확인 중"}
            </strong>
            <small>
              {status
                ? `${status.platform.os} · ${status.platform.machine}`
                : "설치된 서버 기준"}
            </small>
          </span>
          <ChevronRight size={18} />
        </button>
      </div>
      <section className="management-card">
        <SectionHeading
          className="management-card-heading"
          icon={<CheckCircle2 size={21} />}
          title="처음이라면, 이 순서로"
          description="필요한 기능부터 하나씩 준비하세요."
        />
        <div className="management-setup-list">
          {[
            {
              path: "/settings/speech",
              label: "음성을 기록할 모델 준비",
              text: "엔진과 모델 설치 후 새 전사에 적용",
              ready: !!status?.workers.asr?.ready,
            },
            {
              path: "/settings/rag",
              label: "자료를 찾는 방식 조정",
              text: "검색 모델 준비 · 청크 크기와 근거 개수 설정",
            },
            {
              path: "/settings/ai",
              label: "답변을 만들 AI 연결",
              text: "연결할 모델 선택 · 실제 답변으로 연결 확인",
            },
          ].map((x, i) => (
            <button
              key={x.path}
              onClick={() => navigate(x.path as SettingsPath)}
            >
              <span className={`management-step ${x.ready ? "done" : ""}`}>
                {x.ready ? <Check size={18} /> : i + 1}
              </span>
              <span>
                <strong>{x.label}</strong>
                <small>{x.text}</small>
              </span>
              <ArrowRight size={18} />
            </button>
          ))}
        </div>
      </section>
      <ThemeSettings />
      <Preferences />
    </>
  );
}
