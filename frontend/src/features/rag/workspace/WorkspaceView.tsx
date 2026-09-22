import { FeedbackMessage } from "../../../components/ui/FeedbackMessage";
import {
  Folder,
  Layers,
  Loader2,
  RefreshCw,
  Search,
  Settings2,
} from "lucide-react";
import {
  labels,
  reasons,
  type Diagnostics,
  type SearchResult,
  type Workspace,
} from "../api";
import { Badge } from "../components/SourceFiles";
import { busy } from "../utils";
import EvidencePanel from "./EvidencePanel";
import WorkspaceSearch from "./WorkspaceSearch";
import WorkspaceData from "./WorkspaceData";
import WorkspaceSettings from "./WorkspaceSettings";
import { useWorkspaceDetail } from "./useWorkspaceDetail";
import { useWorkspace } from "../../../workspace/context";
export default function WorkspaceView({
  initial,
  initialResult,
  diagnostics,
  onError,
  onRefresh,
  onDeleted,
  onManageAI,
}: {
  initial: Workspace;
  initialResult?: SearchResult;
  diagnostics: Diagnostics | null;
  onError: (s: string) => void;
  onRefresh: () => Promise<unknown>;
  onDeleted: () => void;
  onManageAI: () => void;
}) {
  const { access } = useWorkspace();
  const workspace = useWorkspaceDetail({
    initial,
    initialResult,
    onError,
    onRefresh,
    onDeleted,
  });
  const { ws, tab, setTab, evidence, setEvidence, refresh, cancelJob } =
    workspace;
  const managesData =
    !!ws.can_manage || access.role === "admin" || access.role === "superadmin";
  const job = ws.latest_job;
  const warnings =
    job?.result.files?.filter((f) =>
      ["FAILED", "REVIEWED", "PROCESSED_WITH_WARNINGS"].includes(f.state),
    ).length || 0;
  return (
    <>
      <div className="rag-title-row rag-workspace-heading">
        <div>
          <h1>{ws.name}</h1>
          <p>
            <Folder size={15} />
            {ws.source?.kind === "upload"
              ? `업로드 · ${ws.source.label}`
              : ws.source?.label || "공유 자료"}
            <span className="rag-title-dot">·</span>
            {ws.document_count}개 문서
            {ws.state !== "READY" && <Badge state={ws.state} />}
          </p>
        </div>
        {managesData && (
          <button
            className="rag-secondary"
            disabled={busy(job) || workspace.refreshing}
            onClick={() => void refresh()}
          >
            <RefreshCw size={16} className={busy(job) ? "rag-spin" : ""} />
            {busy(job) ? "자료 준비 중" : "자료 새로고침"}
          </button>
        )}
      </div>
      {diagnostics?.model.state !== "READY" && diagnostics && (
        <FeedbackMessage className="notice">
          자료 검색을 준비하고 있습니다. 잠시 후 다시 시도해 주세요.
        </FeedbackMessage>
      )}
      {managesData && job && (job.state !== "READY" || warnings > 0) && (
        <div className={"rag-job-banner " + (busy(job) ? "" : "warn")}>
          {busy(job) ? (
            <Loader2 className="rag-spin" size={19} />
          ) : (
            <Layers size={19} />
          )}
          <div>
            <strong>
              {job.state === "READY" && warnings > 0
                ? "확인이 필요한 문서가 있습니다"
                : labels[job.state] || "자료 확인 필요"}
            </strong>
            <span>
              {job.result.error_code
                ? reasons[job.result.error_code] ||
                  "자료를 준비하지 못했습니다. 문서를 확인하고 다시 시도해 주세요."
                : warnings
                  ? `${warnings}개 문서를 확인해 주세요.`
                  : busy(job)
                    ? "자료를 등록하고 있습니다. 잠시만 기다려 주세요."
                    : "자료 관리에서 문서를 확인해 주세요."}
              {ws.active_revision_id &&
              ws.active_revision_id !== job.revision_id
                ? " 기존 자료는 계속 검색할 수 있습니다."
                : ""}
            </span>
          </div>
          {busy(job) ? (
            <button onClick={cancelJob} disabled={!!job.cancel}>
              {job.cancel ? "취소 요청됨" : "작업 취소"}
            </button>
          ) : (
            <button onClick={() => setTab("data")}>자료 확인</button>
          )}
        </div>
      )}
      <div className="rag-tabs">
        {[
          ["search", "검색과 질문", Search],
          ["data", "자료 관리", Layers],
          ["settings", "워크스페이스 설정", Settings2],
        ]
          .filter(([id]) => managesData || id === "search")
          .map(([id, title, Icon]) => {
            const I = Icon as typeof Search;
            return (
              <button
                key={id as string}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id as string)}
              >
                <I size={17} />
                {title as string}
              </button>
            );
          })}
      </div>
      {tab === "search" || !managesData ? (
        <WorkspaceSearch
          workspace={workspace}
          diagnostics={diagnostics}
          managesData={managesData}
          managesAI={access.role === "superadmin"}
          onManageAI={onManageAI}
        />
      ) : tab === "data" ? (
        <WorkspaceData workspace={workspace} />
      ) : (
        <WorkspaceSettings workspace={workspace} diagnostics={diagnostics} />
      )}
      {evidence && (
        <EvidencePanel
          key={evidence.evidence_id}
          evidence={evidence}
          onClose={() => setEvidence(null)}
        />
      )}
    </>
  );
}
