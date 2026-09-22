import { useEffect, useState } from "react";
import type { SettingsPath } from "../../../workspace/navigation";
import {
  connectRag,
  errorMessage,
  systemApi,
  type InstallJob,
  type SystemStatus,
} from "../api";

/** Owns system polling and RAG authorization while the page owns navigation. */
export function useManagementSystem(
  credential: string,
  active: boolean,
  sectionPath: SettingsPath,
) {
  const [visited, setVisited] = useState({
    rag: sectionPath === "/settings/rag",
    ai: sectionPath === "/settings/ai",
  });
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [connectionError, setConnectionError] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);
  const [ragReady, setRagReady] = useState(false);
  const [ragError, setRagError] = useState("");
  const [authRetry, setAuthRetry] = useState(0);
  useEffect(() => {
    setNotice("");
    setError("");
    if (active) window.scrollTo(0, 0);
  }, [sectionPath, active]);
  useEffect(() => {
    setVisited((value) => ({
      rag: value.rag || sectionPath === "/settings/rag",
      ai: value.ai || sectionPath === "/settings/ai",
    }));
  }, [sectionPath]);
  useEffect(() => {
    if (!credential || !active) return;
    let alive = true;
    let fetching = false;
    const tick = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const value = await systemApi<SystemStatus>();
        if (alive) {
          setStatus(value);
          setConnectionError("");
        }
      } catch (e) {
        if (alive) setConnectionError(errorMessage(e));
      } finally {
        fetching = false;
      }
    };
    void tick();
    const timer = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [credential, active, authRetry]);
  useEffect(() => {
    if (!credential || (!visited.rag && !visited.ai)) return;
    let alive = true;
    setRagError("");
    connectRag(credential)
      .then(() => {
        if (alive) setRagReady(true);
      })
      .catch((e) => {
        if (alive) setRagError(errorMessage(e));
      });
    return () => {
      alive = false;
    };
  }, [credential, visited.rag, visited.ai, authRetry]);
  async function execute(endpoint: string, body: unknown) {
    if (pending) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const job = await systemApi<InstallJob>(endpoint, body);
      setNotice(
        endpoint === "/install"
          ? "설치를 시작했습니다. 완료 후 ‘이 모델 사용’을 눌러 적용하세요."
          : "모델을 적용하고 있습니다. 아래에서 완료 상태를 확인하세요.",
      );
      setStatus((current) =>
        current
          ? {
              ...current,
              busy: true,
              jobs: [job, ...current.jobs.filter((j) => j.id !== job.id)],
            }
          : current,
      );
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setPending(false);
    }
  }
  return {
    visited,
    status,
    connectionError,
    error,
    notice,
    pending,
    ragReady,
    ragError,
    execute,
    clearError: () => setError(""),
    refresh: () => setAuthRetry((value) => value + 1),
  };
}
