import { Loader2, RefreshCw } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import type { Workspace as RagWorkspace } from "../../rag/api";
import type { RagSettings } from "../api";

const indexFailureMessages: Record<string, string> = {
  FAILED: "실패 · 연결과 자료를 확인하고 다시 시도하세요",
  PARTIAL: "일부 자료 확인 필요 · 자료 검색에서 상세 결과를 확인하세요",
  CANCELLED: "취소됨",
};

type ReindexCardProps = {
  config: RagSettings;
  indexJobs: RagWorkspace[];
  busy: string;
  dirty: boolean;
  embeddingReady: boolean;
  onReindex: (workspace: RagSettings["workspaces"][number]) => Promise<void>;
};

export default function ReindexCard({
  config,
  indexJobs,
  busy,
  dirty,
  embeddingReady,
  onReindex,
}: ReindexCardProps) {
  return (
    <section className="management-card">
      <SectionHeading
        className="management-card-heading"
        icon={<RefreshCw size={21} />}
        title="자료에 변경 내용 반영"
        description="재색인이 끝날 때까지 기존 자료로 계속 검색할 수 있습니다."
      >
        <span className="management-badge">
          {config.workspaces
            .reduce((sum, workspace) => sum + workspace.chunk_count, 0)
            .toLocaleString()}
          개 청크
        </span>
      </SectionHeading>
      {!config.workspaces.length ? (
        <p className="management-muted">
          먼저 자료 검색 화면에서 워크스페이스를 만들고 문서를 추가하세요.
        </p>
      ) : (
        <div className="management-index-list">
          {config.workspaces.map((workspace) => {
            const latestJob = indexJobs.find(
              (item) => item.id === workspace.workspace_id,
            )?.latest_job;
            const failureMessage = latestJob
              ? indexFailureMessages[latestJob.state]
              : undefined;
            return (
              <div key={workspace.workspace_id}>
                <span>
                  <strong>{workspace.name}</strong>
                  {failureMessage && (
                    <small className="management-field-error" role="status">
                      최근 색인: {failureMessage}
                    </small>
                  )}
                  <small>
                    {workspace.chunk_count.toLocaleString()}개 청크 ·{" "}
                    {workspace.indexing
                      ? "재색인 중"
                      : workspace.requires_reindex
                        ? "새 설정 반영 필요"
                        : workspace.active_revision_id
                          ? "최신 설정 반영됨"
                          : "아직 색인 없음"}
                  </small>
                </span>
                <button
                  className="management-secondary"
                  disabled={
                    !!busy ||
                    dirty ||
                    workspace.indexing ||
                    !workspace.has_source ||
                    !embeddingReady
                  }
                  title={
                    dirty
                      ? "먼저 설정을 저장하세요."
                      : !workspace.has_source
                        ? "자료 폴더를 먼저 연결하세요."
                        : undefined
                  }
                  onClick={() => void onReindex(workspace)}
                >
                  {workspace.indexing ? (
                    <>
                      <Loader2 size={16} className="management-spin" />
                      재색인 중
                    </>
                  ) : (
                    <>
                      <RefreshCw size={16} />
                      재색인
                    </>
                  )}
                </button>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
