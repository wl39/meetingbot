import { Layers } from "lucide-react";
import { Badge, Files } from "../components/SourceFiles";
import { busy, time } from "../utils";
import type { WorkspaceDetail } from "./useWorkspaceDetail";

export default function WorkspaceData({
  workspace,
}: {
  workspace: Pick<
    WorkspaceDetail,
    "ws" | "revisions" | "openDocument" | "refresh" | "refreshing"
  >;
}) {
  const { ws, revisions, openDocument, refresh, refreshing } = workspace;
  const job = ws.latest_job;
  return (
    <div className="rag-data-grid">
      <section className="rag-panel">
        <div className="rag-panel-heading">
          <h2>워크스페이스 문서</h2>
          <span>{job?.result.files?.length || 0}개 항목</span>
        </div>
        {job?.state === "PARTIAL" && (
          <div className="rag-review-action">
            <strong>일부 문서를 확인해 주세요.</strong>
            <p>
              아래 표시된 문서를 확인하거나, 읽을 수 있는 문서부터 사용하세요.
            </p>
            <button
              className="rag-primary"
              disabled={refreshing || busy(job)}
              onClick={() => void refresh(true)}
            >
              {refreshing ? "등록 중…" : "사용 가능한 문서로 계속"}
            </button>
          </div>
        )}
        {job?.result.review_accepted && job.state === "READY" && (
          <p className="rag-data-summary">
            확인이 필요한 문서는 원본을 함께 살펴보세요. 읽을 수 없는 파일은
            검색 결과에 포함되지 않습니다.
          </p>
        )}
        <Files
          pinIssues
          files={job?.result.files}
          onOpen={
            job && ["READY", "PARTIAL"].includes(job.state) && job.revision_id
              ? (path) => void openDocument(path, job.revision_id!)
              : undefined
          }
        />
      </section>
      <section className="rag-panel rag-version-list">
        <h2>업데이트 기록</h2>
        <p>자료를 등록하거나 새로고침한 내역입니다.</p>
        {revisions.map((r) => (
          <div key={r.id}>
            <Layers size={18} />
            <span>
              <strong>
                {time(r.created_at)}{" "}
                {r.id === ws.active_revision_id && <em>사용 중</em>}
              </strong>
              <small>{r.manifest.documents?.length ?? 0}개 문서</small>
            </span>
            {r.state !== "READY" && <Badge state={r.state} />}
          </div>
        ))}
      </section>
    </div>
  );
}
