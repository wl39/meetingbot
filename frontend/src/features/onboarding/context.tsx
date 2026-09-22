import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Workspace } from "../rag/api";
import { useWorkspace } from "../../workspace/context";
import {
  initialTutorial,
  restoreTutorial,
  tutorialStorageKey,
  type TutorialState,
  type TutorialStep,
} from "./state";

type Request = {
  id: number;
  type: "create" | "workspace" | "query";
  workspaceId?: string;
  query?: string;
};
type Tutorial = {
  state: TutorialState;
  active: boolean;
  workspaceId: string | null;
  request: Request | null;
  audioFile: File | null;
  audioSessionId: string | null;
  begin: (source: "own" | "sample") => void;
  restart: () => void;
  dismiss: () => void;
  go: (step: TutorialStep) => void;
  setSource: (source: "own" | "sample") => void;
  openCreate: () => void;
  openWorkspace: () => void;
  fillQuery: () => void;
  selectWorkspace: (
    workspace: Workspace,
    query?: string,
    voicePrompt?: string,
  ) => void;
  reportWorkspace: (workspace: Workspace) => void;
  reportSearch: (workspaceId: string) => void;
  reportVoice: (file?: File, sessionId?: string) => void;
  forgetVoice: (sessionId: string) => void;
  reportFile: () => void;
};
const Context = createContext<Tutorial | null>(null);
export const useOnboarding = () => useContext(Context);

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const { access, navigate, busyMode } = useWorkspace();
  const storageKey = tutorialStorageKey(access.account?.id || "local");
  const [state, setState] = useState(() => {
    try {
      return restoreTutorial(localStorage.getItem(storageKey));
    } catch {
      return { ...initialTutorial };
    }
  });
  const [audioRecording, setAudioRecording] = useState<{
    sessionId: string;
    file: File;
  } | null>(null);
  const [request, setRequest] = useState<Request | null>(() =>
    state.workspaceId && state.step === "search"
      ? {
          id: 1,
          type: "workspace",
          workspaceId: state.workspaceId,
          query: state.query,
        }
      : null,
  );
  const active = !["welcome", "done", "dismissed"].includes(state.step);
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(state));
    } catch {
      /* Private browsing can disable persistence. */
    }
  }, [state, storageKey]);
  const issue = useCallback((next: Omit<Request, "id">) => {
    setRequest((previous) => ({ ...next, id: (previous?.id || 0) + 1 }));
  }, []);
  const selectWorkspace = useCallback(
    (workspace: Workspace, query?: string, voicePrompt?: string) => {
      const question = query || initialTutorial.query;
      setState((previous) => ({
        ...previous,
        step: "search",
        workspaceId: workspace.id,
        workspaceName: workspace.name,
        query: question,
        voicePrompt: voicePrompt || initialTutorial.voicePrompt,
        searched: false,
        recorded: false,
        uploaded: false,
      }));
      issue({ type: "workspace", workspaceId: workspace.id, query: question });
      navigate("/rag");
    },
    [issue, navigate],
  );
  const reportWorkspace = useCallback(
    (workspace: Workspace) => {
      if (state.step === "documents") selectWorkspace(workspace);
    },
    [state.step, selectWorkspace],
  );
  const reportSearch = useCallback((workspaceId: string) => {
    setState((previous) =>
      previous.step === "search" &&
      previous.workspaceId === workspaceId &&
      !previous.searched
        ? { ...previous, searched: true }
        : previous,
    );
  }, []);
  const reportVoice = useCallback((file?: File, sessionId?: string) => {
    if (file && sessionId) setAudioRecording({ file, sessionId });
    setState((previous) =>
      previous.step === "voice" && !previous.recorded
        ? { ...previous, recorded: true }
        : previous,
    );
  }, []);
  const forgetVoice = useCallback((sessionId: string) => {
    setAudioRecording((previous) =>
      previous?.sessionId === sessionId ? null : previous,
    );
  }, []);
  const reportFile = useCallback(() => {
    setState((previous) =>
      previous.step === "file" && !previous.uploaded
        ? { ...previous, uploaded: true }
        : previous,
    );
  }, []);
  const value = useMemo<Tutorial>(
    () => ({
      state,
      active,
      workspaceId: state.workspaceId,
      request,
      audioFile: audioRecording?.file ?? null,
      audioSessionId: audioRecording?.sessionId ?? null,
      begin(source) {
        setState((previous) => ({ ...previous, step: "documents", source }));
        navigate("/rag");
      },
      restart() {
        if (!busyMode) {
          setState({ ...initialTutorial });
          setRequest(null);
          setAudioRecording(null);
        }
      },
      dismiss() {
        setState((previous) => ({ ...previous, step: "dismissed" }));
        setRequest(null);
        setAudioRecording(null);
      },
      go(step) {
        if (
          busyMode &&
          ((step === "voice" && busyMode !== "live") ||
            (step === "file" && busyMode !== "file"))
        )
          return;
        setState((previous) => ({ ...previous, step }));
        if (step === "voice") navigate("/live");
        else if (step === "file") navigate("/");
        else if (step === "documents" || step === "search") {
          navigate("/rag");
          if (step === "search" && state.workspaceId)
            issue({ type: "workspace", workspaceId: state.workspaceId });
        }
      },
      setSource(source) {
        setState((previous) => ({ ...previous, source }));
      },
      openCreate() {
        issue({ type: "create" });
        navigate("/rag");
      },
      openWorkspace() {
        if (state.workspaceId) {
          issue({ type: "workspace", workspaceId: state.workspaceId });
          navigate("/rag");
        }
      },
      fillQuery() {
        if (state.workspaceId) {
          issue({
            type: "query",
            workspaceId: state.workspaceId,
            query: state.query,
          });
          navigate("/rag");
        }
      },
      selectWorkspace,
      reportWorkspace,
      reportSearch,
      reportVoice,
      forgetVoice,
      reportFile,
    }),
    [
      state,
      active,
      request,
      audioRecording,
      busyMode,
      navigate,
      issue,
      selectWorkspace,
      reportWorkspace,
      reportSearch,
      reportVoice,
      forgetVoice,
      reportFile,
    ],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
