import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  AudioLines,
  BookOpen,
  ChevronDown,
  FileAudio,
  KeyRound,
  Mic,
  Settings2,
} from "lucide-react";
import App from "../App";
import {
  canNavigate,
  workspacePath,
  workspaceView,
  type RagPath,
  type SttMode,
  type WorkspacePath,
} from "./navigation";
import { WorkspaceContext } from "./context";
import { roleLabels, useAccess } from "./access";
import "./workspace.css";
import { setTelemetryReady, track } from "./telemetry";
import { refreshTheme } from "./theme";
import { OnboardingProvider } from "../features/onboarding/context";
import OnboardingGuide, {
  TutorialButton,
} from "../features/onboarding/OnboardingGuide";

const RagPage = lazy(() => import("../features/rag/RagPage"));
const ManagementPage = lazy(
  () => import("../features/management/ManagementPage"),
);

export default function Workspace() {
  useEffect(() => {
    const refresh = () => {
      if (!document.hidden) void refreshTheme().catch(() => {});
    };
    refresh();
    const timer = setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => {
      clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  const [path, setPath] = useState(() => workspacePath(location.pathname));
  const view = workspaceView(path);
  const [sttMode, setSttMode] = useState<SttMode>(
    view === "live" ? "live" : "file",
  );
  const [ragPath, setRagPath] = useState<RagPath>(
    path.startsWith("/rag") ? (path as RagPath) : "/rag",
  );
  const [visited, setVisited] = useState({
    stt: view === "file" || view === "live",
    rag: view === "rag",
    settings: view === "settings",
  });
  const [busyMode, setBusyMode] = useState<SttMode | null>(null);
  const [credential, setCredential] = useState(
    () => sessionStorage.getItem("stt-token") || "",
  );
  const { access, error: accessError } = useAccess(credential);
  useEffect(() => {
    setTelemetryReady(!!access?.authenticated);
  }, [access]);
  useEffect(() => {
    track("navigation");
  }, [path]);
  useEffect(() => {
    if (access?.keyless && !access.authenticated && credential) {
      sessionStorage.removeItem("stt-token");
      setCredential("");
    }
  }, [access, credential]);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginKey, setLoginKey] = useState("");
  const topRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const top = topRef.current;
    if (!top) return;
    const observer = new ResizeObserver(() =>
      top.parentElement?.style.setProperty(
        "--workspace-top-height",
        `${top.getBoundingClientRect().height}px`,
      ),
    );
    observer.observe(top);
    return () => observer.disconnect();
  }, [access?.demo, access?.role]);
  const scroll = useRef({ stt: 0, rag: 0, settings: 0 });
  const group: "rag" | "settings" | "stt" =
    view === "rag" ? "rag" : view === "settings" ? "settings" : "stt";
  const currentGroup = useRef(group);
  const connect = useCallback((key: string) => {
    const value = key.trim();
    if (!value) {
      const previous = sessionStorage.getItem("stt-token");
      if (previous)
        void fetch("/api/rag/auth/logout", {
          method: "POST",
          headers: { Authorization: `Bearer ${previous}` },
        }).catch(() => {});
    }
    if (value) sessionStorage.setItem("stt-token", value);
    else sessionStorage.removeItem("stt-token");
    setCredential(value);
  }, []);
  const applyPath = useCallback((next: WorkspacePath) => {
    const nextView = workspaceView(next);
    scroll.current[currentGroup.current] = window.scrollY;
    setPath(next);
    if (nextView === "rag") setRagPath(next as RagPath);
    else if (nextView === "file" || nextView === "live") setSttMode(nextView);
    setVisited((current) => ({
      ...current,
      [nextView === "rag"
        ? "rag"
        : nextView === "settings"
          ? "settings"
          : "stt"]: true,
    }));
  }, []);
  const navigate = useCallback(
    (next: WorkspacePath) => {
      if (!canNavigate(next, busyMode)) return;
      const canonical = workspacePath(next);
      if (location.pathname !== canonical)
        window.history.pushState(null, "", canonical);
      applyPath(canonical);
    },
    [applyPath, busyMode],
  );
  useEffect(() => {
    const onBack = () => {
      const next = workspacePath(location.pathname);
      if (canNavigate(next, busyMode)) applyPath(next);
      else window.history.replaceState(null, "", path);
    };
    window.addEventListener("popstate", onBack);
    return () => window.removeEventListener("popstate", onBack);
  }, [applyPath, busyMode, path]);
  useLayoutEffect(() => {
    currentGroup.current = group;
    window.scrollTo(0, scroll.current[group]);
  }, [group]);
  useEffect(() => {
    document.title =
      view === "settings"
        ? "설정 및 관리"
        : view === "rag"
          ? "자료 검색"
          : view === "live"
            ? "실시간 전사"
            : "파일 전사";
  }, [path, view]);

  if (!access)
    return (
      <div className="workspace-loading" role="status">
        {accessError || "불러오는 중…"}
      </div>
    );
  return (
    <WorkspaceContext.Provider
      value={{
        access,
        view,
        sttMode,
        ragPath,
        busyMode,
        setBusyMode,
        navigate,
        credential,
        connect,
      }}
    >
      <OnboardingProvider key={access.account?.id || credential || "local"}>
        <div className="unified-workspace" data-view={view}>
          <div className="workspace-top" ref={topRef}>
            <header
              className={`workspace-header ${access.demo && !credential ? "is-guest" : ""}`}
            >
              <button
                className="workspace-brand"
                aria-label="자료 라이브러리 홈"
                onClick={() => navigate("/rag")}
              >
                <span className="brand-symbol">
                  <AudioLines size={23} />
                </span>
              </button>
              <nav
                className="workspace-navigation"
                aria-label="워크스페이스 화면 전환"
              >
                {(
                  [
                    {
                      view: "file",
                      path: "/",
                      label: "파일 전사",
                      Icon: FileAudio,
                    },
                    {
                      view: "live",
                      path: "/live",
                      label: "실시간 전사",
                      Icon: Mic,
                    },
                    {
                      view: "rag",
                      path: ragPath,
                      label: "자료 검색",
                      Icon: BookOpen,
                    },
                  ] as const
                ).map((item) => (
                  <button
                    key={item.view}
                    className={view === item.view ? "selected" : ""}
                    aria-current={view === item.view ? "page" : undefined}
                    aria-controls={
                      item.view === "rag" ? "rag-workspace" : "stt-workspace"
                    }
                    disabled={!canNavigate(item.path, busyMode)}
                    onClick={() => navigate(item.path)}
                  >
                    <item.Icon size={18} aria-hidden="true" />
                    {item.label}
                    {busyMode === item.view && (
                      <span className="workspace-busy-dot" />
                    )}
                  </button>
                ))}
              </nav>
              {(access.role === "superadmin" || !access.authenticated) && (
                <button
                  className={`workspace-settings-link ${view === "settings" ? "selected" : ""}`}
                  aria-current={view === "settings" ? "page" : undefined}
                  aria-label="설정 및 관리"
                  aria-controls="settings-workspace"
                  onClick={() => navigate("/settings")}
                >
                  <Settings2 size={19} aria-hidden="true" />
                  <span>설정 및 관리</span>
                </button>
              )}
              <div className="workspace-account">
                <TutorialButton />
                {access.role && (
                  <span className="role-badge">
                    {access.demo && !credential
                      ? "게스트"
                      : roleLabels[access.role]}
                  </span>
                )}
                <button
                  className="workspace-login"
                  aria-label={
                    credential
                      ? "접속 정보 변경"
                      : access.authenticated
                        ? "관리자 로그인"
                        : "로그인"
                  }
                  disabled={!!busyMode}
                  onClick={() => setLoginOpen(true)}
                >
                  <KeyRound size={16} aria-hidden="true" />
                  <span>
                    {credential
                      ? "접속 정보 변경"
                      : access.authenticated
                        ? "관리자 로그인"
                        : "로그인"}
                  </span>
                </button>
                {credential && (
                  <button disabled={!!busyMode} onClick={() => connect("")}>
                    로그아웃
                  </button>
                )}
              </div>
              {busyMode && (
                <span className="workspace-hint" role="status">
                  {busyMode === "live" ? "녹음 중" : "파일 업로드 중"}
                </span>
              )}
            </header>
            {access.demo && (
              <details className="demo-banner">
                <summary aria-label="공개 데모 이용 안내">
                  <strong>공개 데모</strong>
                  <span>
                    키 없이 체험 · 음성 {access.limits.seconds / 60}분 /{" "}
                    {access.limits.file_mb}MB
                  </span>
                  <ChevronDown size={18} aria-hidden="true" />
                </summary>
                <div className="demo-banner-details">
                  <p>
                    동시 전사 1건 · 방문자당 하루{" "}
                    {access.limits.jobs_per_visitor}회
                  </p>
                  <p>
                    체험 기록은 이 브라우저에서만 보이며 관리자는 확인할 수
                    있습니다. 기록은 24시간 후 자동 정리됩니다.
                  </p>
                </div>
              </details>
            )}
          </div>
          <OnboardingGuide />
          {loginOpen && (
            <div className="access-dialog-backdrop">
              <section
                className="access-dialog"
                role="dialog"
                aria-modal="true"
                aria-labelledby="access-login-title"
              >
                <h2 id="access-login-title">워크스페이스 접속</h2>
                <p>
                  {access.keyless
                    ? "일반 사용은 키 없이 가능합니다. 관리자 기능을 사용하려면 접속 키를 입력하세요."
                    : "초대받은 접속 코드를 입력하세요."}
                </p>
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    connect(loginKey);
                    setLoginKey("");
                    setLoginOpen(false);
                  }}
                >
                  <input
                    autoFocus
                    aria-label="접속 키"
                    type="password"
                    autoComplete="off"
                    value={loginKey}
                    onChange={(e) => setLoginKey(e.target.value)}
                  />
                  <button className="primary" disabled={!loginKey.trim()}>
                    로그인
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setLoginOpen(false);
                      setLoginKey("");
                    }}
                  >
                    닫기
                  </button>
                </form>
              </section>
            </div>
          )}
          <div id="stt-workspace" hidden={view !== "file" && view !== "live"}>
            {visited.stt && <App key={credential} />}
          </div>
          <div id="settings-workspace" hidden={view !== "settings"}>
            {visited.settings &&
            access.authenticated &&
            access.role !== "superadmin" ? (
              <div className="workspace-loading">
                서비스 운영 설정은 운영 관리자만 이용할 수 있습니다.
              </div>
            ) : (
              visited.settings && (
                <Suspense
                  fallback={
                    <div className="workspace-loading" role="status">
                      관리 화면을 불러오는 중…
                    </div>
                  }
                >
                  <ManagementPage
                    key={credential}
                    path={path}
                    active={view === "settings"}
                  />
                </Suspense>
              )
            )}
          </div>
          <div id="rag-workspace" hidden={view !== "rag"}>
            {visited.rag && (
              <Suspense
                fallback={
                  <div className="workspace-loading" role="status">
                    자료 라이브러리를 불러오는 중…
                  </div>
                }
              >
                <RagPage key={credential} />
              </Suspense>
            )}
          </div>
        </div>
      </OnboardingProvider>
    </WorkspaceContext.Provider>
  );
}
