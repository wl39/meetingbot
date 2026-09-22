import { Download, Monitor } from "lucide-react";
import type { SystemStatus } from "./api";
import { bytes, engineName } from "./format";
import { SectionHeading } from "../../components/ui/SectionHeading";
import JobList from "./components/JobList";
import RemoteAccessCard from "./components/RemoteAccessCard";
export default function UpdatesSection({
  status,
}: {
  status: SystemStatus | null;
}) {
  return (
    <>
      <RemoteAccessCard access={status?.access} />
      <section className="management-card">
        <SectionHeading
          className="management-card-heading"
          icon={<Monitor size={22} />}
          title="설치된 환경"
          description="지금 접속한 서버의 상태입니다."
        >
          <span className="management-badge">설치형 워크스페이스</span>
        </SectionHeading>
        <dl className="management-environment">
          <div>
            <dt>운영체제</dt>
            <dd>
              {status
                ? `${status.platform.os} · ${status.platform.machine}`
                : "확인 중"}
            </dd>
          </div>
          <div>
            <dt>음성 엔진</dt>
            <dd>{engineName(status?.selection.engine)}</dd>
          </div>
          <div>
            <dt>남은 저장 공간</dt>
            <dd>{status ? bytes(status.storage.free_bytes) : "확인 중"}</dd>
          </div>
          <div>
            <dt>모델 관리</dt>
            <dd>웹에서 설치 · 선택 · 적용</dd>
          </div>
        </dl>
      </section>
      <section className="management-card">
        <SectionHeading
          className="management-card-heading"
          icon={<Download size={22} />}
          title="프로그램 업데이트"
          description="음성 모델 설치와 프로그램 자체 업데이트는 따로 관리합니다."
        >
          <span className="management-badge">배포 채널 준비 중</span>
        </SectionHeading>
        <p className="management-muted">
          현재 개발 설치에는 배포 버전을 확인하고 교체하는 업데이트 채널이 아직
          연결되지 않았습니다. 프로그램 자동 업데이트는 사용할 수 없으며, 모델
          설치와 변경은 이 웹 화면에서 진행할 수 있습니다.
        </p>
        <details className="management-details">
          <summary>설치와 업데이트 적용 범위</summary>
          <ul>
            <li>음성 인식 엔진·모델: 설치 및 전환 후 새 전사에 적용</li>
            <li>자료 청크 설정: 저장 후 워크스페이스 재색인으로 반영</li>
            <li>AI 연결 모델·답변 설정: 저장 후 다음 답변부터 적용</li>
            <li>
              프로그램 자체: 버전 배포와 복구를 지원하는 업데이트 채널 연결 필요
            </li>
          </ul>
        </details>
      </section>
      <section className="management-card">
        <SectionHeading
          className="management-card-heading"
          icon={<Download size={22} />}
          title="최근 설치 기록"
          description="백그라운드 설치와 모델 적용 결과를 확인하세요."
        />
        <JobList jobs={status?.jobs || []} />
      </section>
    </>
  );
}
