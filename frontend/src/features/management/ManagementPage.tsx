import { CheckCircle2, ChevronRight, Loader2, RefreshCw } from "lucide-react";
import { useWorkspace } from "../../workspace/context";
import type { SettingsPath, WorkspacePath } from "../../workspace/navigation";
import LlmSettings from "../rag/LlmSettings";
import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import { sections } from "./sections";
import { useManagementSystem } from "./hooks/useManagementSystem";
import ManagementSidebar from "./components/ManagementSidebar";
import ManagementLogin from "./components/ManagementLogin";
import OverviewSection from "./OverviewSection";
import SpeechSection from "./SpeechSection";
import RetrievalSection from "./RetrievalSection";
import UpdatesSection from "./UpdatesSection";
import "../rag/rag.css";
import "./management.css";
import AccessSection from "./AccessSection";

export default function ManagementPage({
  path,
  active,
}: {
  path: WorkspacePath;
  active: boolean;
}) {
  const { credential, connect, navigate } = useWorkspace();
  const sectionPath = path.startsWith("/settings")
    ? (path as SettingsPath)
    : "/settings";
  const section =
    sections.find((item) => item.path === sectionPath) || sections[0];
  const {
    visited,
    status,
    connectionError,
    error,
    notice,
    pending,
    ragReady,
    ragError,
    execute,
    clearError,
    refresh,
  } = useManagementSystem(credential, active, sectionPath);
  return (
    <div className="management-shell">
      <ManagementSidebar sectionPath={sectionPath} navigate={navigate} />
      <main className="management-main">
        <div className="management-breadcrumb">
          워크스페이스 <ChevronRight size={14} /> 설정 및 관리{" "}
          <ChevronRight size={14} />
          {section.label}
        </div>
        <div className="management-content">
          <header className="management-page-title">
            <div>
              <h1>
                {section.label === "관리 홈" ? "설정 및 관리" : section.label}
              </h1>
              <p>{section.description}</p>
            </div>
            <button
              className="management-refresh"
              aria-label="서버 상태 새로고침"
              onClick={refresh}
            >
              <RefreshCw size={18} />
              <span>상태 새로고침</span>
            </button>
          </header>
          {connectionError && (
            <FeedbackMessage className="management-error" tone="error">
              <span>{connectionError}</span>
              {connectionError.includes("접속 키") && (
                <button onClick={() => connect("")}>접속 키 다시 입력</button>
              )}
            </FeedbackMessage>
          )}
          {error && (
            <FeedbackMessage
              className="management-error"
              tone="error"
              onDismiss={clearError}
              dismissLabel="관리 오류 닫기"
            >
              <span>{error}</span>
            </FeedbackMessage>
          )}
          {notice && (
            <FeedbackMessage
              className="management-notice"
              icon={<CheckCircle2 size={18} />}
            >
              {notice}
            </FeedbackMessage>
          )}
          {!credential ? (
            <ManagementLogin connect={connect} />
          ) : (
            <>
              {sectionPath === "/settings/access" && <AccessSection />}
              {sectionPath === "/settings" && (
                <OverviewSection status={status} navigate={navigate} />
              )}
              {sectionPath === "/settings/speech" && (
                <SpeechSection
                  status={status}
                  pending={pending}
                  execute={execute}
                />
              )}
              {(sectionPath === "/settings/rag" ||
                sectionPath === "/settings/ai") &&
                !ragReady && (
                  <div
                    className="management-empty"
                    role={ragError ? "alert" : "status"}
                  >
                    {ragError ? (
                      <>
                        <p>{ragError}</p>
                        <button onClick={refresh}>다시 연결</button>
                      </>
                    ) : (
                      <>
                        <Loader2 size={20} className="management-spin" />
                        자료 서비스에 연결하는 중…
                      </>
                    )}
                  </div>
                )}
              <div hidden={sectionPath !== "/settings/rag"}>
                {ragReady && visited.rag && (
                  <RetrievalSection
                    active={active && sectionPath === "/settings/rag"}
                  />
                )}
              </div>
              <div
                className="management-ai"
                hidden={sectionPath !== "/settings/ai"}
              >
                {ragReady && visited.ai && (
                  <LlmSettings onBack={() => navigate("/settings")} />
                )}
              </div>
              {sectionPath === "/settings/updates" && (
                <UpdatesSection status={status} />
              )}
            </>
          )}
        </div>
      </main>
    </div>
  );
}
