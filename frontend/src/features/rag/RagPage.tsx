import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import { useEffect, useState } from "react";
import {
  BookOpen,
  ChevronRight,
  Folder,
  History,
  KeyRound,
  LogOut,
  Plus,
  Settings2,
  Users,
} from "lucide-react";
import "./rag.css";
import { useWorkspace } from "../../workspace/context";
import { message } from "./utils";
import LlmSettings from "./LlmSettings";
import CreateWorkspace from "./sources/CreateWorkspace";
import WorkspaceView from "./workspace/WorkspaceView";
import LibraryOverview from "./library/LibraryOverview";
import { useRagLibrary } from "./library/useRagLibrary";
import QuestionHistory from "./history/QuestionHistory";
import type { SearchResult } from "./api";
import { rememberQuestion } from "./history/bookmark";
import { useOnboarding } from "../onboarding/context";
export default function RagPage() {
  const { ragPath, navigate, credential, connect, busyMode, access } =
    useWorkspace();
  const manageAI = ragPath === "/rag/settings";
  const showingHistory =
    ragPath === "/rag/history" || ragPath === "/rag/history/all";
  const allHistory = ragPath === "/rag/history/all";
  const [historyEntry, setHistoryEntry] = useState<SearchResult | undefined>();
  const setManageAI = (value: boolean) =>
    navigate(value ? "/rag/settings" : "/rag");
  const {
    auth,
    checking,
    key,
    error,
    workspaces,
    selected,
    create,
    diagnostics,
    setKey,
    setError,
    setSelected,
    setCreate,
    login,
    logout,
    reload,
  } = useRagLibrary(credential, connect, access.account?.id);
  const active = workspaces.find((w) => w.id === selected);
  const onboarding = useOnboarding();
  const onboardingRequest = onboarding?.request;
  useEffect(() => {
    if (!auth || !onboardingRequest) return;
    setHistoryEntry(undefined);
    navigate("/rag");
    if (onboardingRequest.type === "create") {
      setSelected(null);
      setCreate(true);
      return;
    }
    if (!onboardingRequest.workspaceId) return;
    setCreate(false);
    setSelected(onboardingRequest.workspaceId);
    void reload().catch((error) => setError(message(error)));
  }, [auth, onboardingRequest?.id]);
  function continueQuestion(entry: SearchResult) {
    setHistoryEntry(entry);
    setSelected(entry.workspace_id);
    setCreate(false);
    navigate("/rag");
  }
  return (
    <div className="rag-shell">
      <aside className="rag-sidebar">
        <div className="rag-nav-label">라이브러리</div>
        <button
          className={
            "rag-library-nav " +
            (!manageAI && !showingHistory ? "selected" : "")
          }
          onClick={() => {
            setManageAI(false);
            setSelected(null);
            setHistoryEntry(undefined);
            setCreate(false);
          }}
        >
          <BookOpen size={19} />
          자료 라이브러리
        </button>
        <button
          className={
            "rag-ai-nav " + (showingHistory && !allHistory ? "selected" : "")
          }
          disabled={!auth}
          onClick={() => navigate("/rag/history")}
        >
          <History size={18} />내 질문 기록
        </button>
        {(access.role === "admin" || access.role === "superadmin") && (
          <button
            className={"rag-ai-nav " + (allHistory ? "selected" : "")}
            disabled={!auth}
            onClick={() => navigate("/rag/history/all")}
          >
            <Users size={18} />
            전체 질문 기록
          </button>
        )}
        {access.role === "superadmin" && (
          <button
            className={"rag-ai-nav " + (manageAI ? "selected" : "")}
            disabled={!auth}
            onClick={() => setManageAI(true)}
          >
            <Settings2 size={18} />
            서비스 운영
          </button>
        )}
        <div className="rag-workspace-title">
          내 워크스페이스
          {auth && (
            <button
              aria-label="워크스페이스 추가"
              disabled={!auth}
              onClick={() => {
                setManageAI(false);
                setCreate(true);
              }}
            >
              <Plus size={17} />
            </button>
          )}
        </div>
        <div className="rag-spaces">
          {workspaces.map((w) => (
            <button
              key={w.id}
              className={selected === w.id ? "selected" : ""}
              onClick={() => {
                setManageAI(false);
                setSelected(w.id);
                onboarding?.reportWorkspace(w);
                setHistoryEntry(undefined);
                setCreate(false);
                setError("");
              }}
            >
              <Folder size={17} />
              <span>
                {w.name}
                <small>{w.document_count}개 문서</small>
              </span>
              {selected === w.id && <ChevronRight size={14} />}
            </button>
          ))}
          {auth && !workspaces.length && (
            <p>
              폴더를 연결해 첫 번째
              <br />
              워크스페이스를 만들어 보세요.
            </p>
          )}
        </div>
      </aside>
      <main className="rag-main">
        <header className="rag-topbar">
          <span>
            워크스페이스 <ChevronRight size={13} />
            {manageAI
              ? "서비스 운영"
              : showingHistory
                ? allHistory
                  ? "전체 질문 기록"
                  : "내 질문 기록"
                : "자료 라이브러리"}
          </span>
          <div>
            {auth && credential && (
              <button
                aria-label="로그아웃"
                disabled={!!busyMode}
                title={
                  busyMode
                    ? "진행 중인 녹음이나 파일 작업을 먼저 마쳐 주세요."
                    : "워크스페이스 로그아웃"
                }
                onClick={logout}
              >
                <LogOut size={16} />
              </button>
            )}
          </div>
        </header>
        <div className="rag-content">
          {error && (
            <FeedbackMessage
              tone="error"
              className="rag-alert"
              onDismiss={() => setError("")}
              dismissLabel="오류 닫기"
            >
              {error}
            </FeedbackMessage>
          )}
          {checking && !auth ? (
            <div className="rag-empty" role="status">
              자료 라이브러리에 연결하는 중…
            </div>
          ) : !auth ? (
            <div className="rag-login">
              <span className="rag-hero-icon">
                <KeyRound size={30} />
              </span>
              <h1>워크스페이스에 로그인</h1>
              <p>
                자료를 검색하고 질문하려면 로그인하세요.
                <br />
                초대받은 워크스페이스의 자료를 확인하세요.
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  login(key).catch((e) => setError(message(e)));
                }}
              >
                <label htmlFor="rag-key">워크스페이스 접속 키</label>
                <input
                  id="rag-key"
                  type="password"
                  autoComplete="current-password"
                  placeholder="접속 키를 입력하세요"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                />
                <button
                  className="rag-primary"
                  disabled={checking || !key.trim()}
                >
                  {checking ? "연결 확인 중…" : "로그인"}
                  <ChevronRight size={17} />
                </button>
              </form>
            </div>
          ) : showingHistory ? (
            <QuestionHistory
              key={ragPath}
              all={allHistory}
              onContinue={(entry) => {
                if (!allHistory && access.account)
                  rememberQuestion(access.account.id, "mine", entry.request_id);
                continueQuestion(entry);
              }}
            />
          ) : manageAI && access.role === "superadmin" ? (
            <LlmSettings
              onBack={() => {
                setManageAI(false);
              }}
            />
          ) : create ? (
            <CreateWorkspace
              onClose={() => setCreate(false)}
              onError={setError}
              onCreated={async (w) => {
                await reload();
                setManageAI(false);
                setSelected(w.id);
                setCreate(false);
                onboarding?.reportWorkspace(w);
              }}
            />
          ) : active ? (
            <WorkspaceView
              key={active.id + (historyEntry?.request_id || "")}
              initial={active}
              initialResult={
                historyEntry?.workspace_id === active.id
                  ? historyEntry
                  : undefined
              }
              diagnostics={diagnostics}
              onError={setError}
              onRefresh={reload}
              onManageAI={() => setManageAI(true)}
              onDeleted={() => {
                setSelected(null);
                void reload();
              }}
            />
          ) : (
            <LibraryOverview
              workspaces={workspaces}
              onContinue={continueQuestion}
              onSelect={(id) => {
                setHistoryEntry(undefined);
                setSelected(id);
                const workspace = workspaces.find((item) => item.id === id);
                if (workspace) onboarding?.reportWorkspace(workspace);
              }}
              onCreate={() => {
                setManageAI(false);
                setCreate(true);
              }}
            />
          )}
        </div>
      </main>
    </div>
  );
}
