import { HardDrive, ShieldCheck, Trash2 } from "lucide-react";
import type { Diagnostics } from "../api";
import type { WorkspaceDetail } from "./useWorkspaceDetail";
import WorkspaceGuideEditor from "./WorkspaceGuideEditor";

export default function WorkspaceSettings({
  workspace,
  diagnostics,
}: {
  workspace: Pick<
    WorkspaceDetail,
    | "ws"
    | "proxy"
    | "confirmDelete"
    | "setConfirmDelete"
    | "updateConsent"
    | "checkConnection"
    | "deleteWorkspace"
  >;
  diagnostics: Diagnostics | null;
}) {
  const {
    ws,
    confirmDelete,
    setConfirmDelete,
    updateConsent,
    deleteWorkspace,
  } = workspace;
  return (
    <div className="rag-settings-grid">
      <WorkspaceGuideEditor key={ws.id} workspaceId={ws.id} />
      <section className="rag-panel rag-setting">
        <h2>
          <ShieldCheck size={20} />
          문서 활용
        </h2>
        <p>등록된 문서를 질문에 답하고 회의 내용을 검토하는 데 활용합니다.</p>
        <label className="rag-consent">
          <input
            type="checkbox"
            checked={ws.consent === diagnostics?.llm.provider_id}
            disabled={!diagnostics?.llm.global_allowed && !ws.consent}
            onChange={(e) =>
              updateConsent(e.target.checked, diagnostics?.llm.provider_id)
            }
          />
          질문과 회의 검토에 이 문서 활용
        </label>
      </section>
      <section className="rag-panel rag-setting">
        <h2>
          <HardDrive size={20} />
          자료 관리
        </h2>
        <dl>
          <dt>질문 기록 보관</dt>
          <dd>{diagnostics ? `${diagnostics.history_days}일` : "확인 중"}</dd>
        </dl>
        <p>
          문서가 변경되었다면 ‘자료 새로고침’으로 최신 내용을 반영하세요. 공유
          폴더의 접근 권한이 변경되면 문서 이용이 제한될 수 있습니다.
        </p>
        <div className="rag-danger">
          <h3>워크스페이스 삭제</h3>
          <p>
            {ws.source?.kind === "upload"
              ? "업로드한 자료와 질문 기록을 삭제합니다. 이 기기의 원본은 유지됩니다."
              : "이 워크스페이스와 질문 기록을 삭제합니다. 원본 폴더는 보존합니다."}
          </p>
          {confirmDelete ? (
            <div>
              <button className="rag-delete" onClick={deleteWorkspace}>
                이 워크스페이스 삭제
              </button>
              <button
                className="rag-secondary"
                onClick={() => setConfirmDelete(false)}
              >
                취소
              </button>
            </div>
          ) : (
            <button
              className="rag-delete"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 size={15} />
              삭제
            </button>
          )}
        </div>
      </section>
    </div>
  );
}
