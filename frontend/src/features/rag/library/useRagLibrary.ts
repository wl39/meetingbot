import { useEffect, useRef, useState } from "react";
import { api, setCsrf, type Diagnostics, type Workspace } from "../api";
import { message } from "../utils";
import { readResume, rememberWorkspace } from "../history/resume";

export function useRagLibrary(
  credential: string,
  connect: (key: string) => void,
  accountId?: string,
) {
  const [auth, setAuth] = useState(false),
    [checking, setChecking] = useState(true),
    [key, setKey] = useState(""),
    [error, setError] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]),
    [selected, updateSelected] = useState<string | null>(
      () => readResume(accountId)?.workspaceId || null,
    ),
    [create, setCreate] = useState(false),
    [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const initialized = useRef<string | null>(null);
  function setSelected(id: string | null) {
    rememberWorkspace(accountId, id);
    updateSelected(id);
  }
  async function login(value: string) {
    const result = await api<{ csrf: string }>("/auth/login", { key: value });
    setCsrf(result.csrf);
    setAuth(true);
    connect(value);
    setKey("");
    setError("");
  }
  useEffect(() => {
    if (initialized.current === credential) return;
    initialized.current = credential;
    setChecking(true);
    api<{ csrf: string }>("/auth/session")
      .then((r) => {
        setCsrf(r.csrf);
        setAuth(true);
      })
      .catch(async () => {
        if (credential) await login(credential);
      })
      .catch(() => {})
      .finally(() => setChecking(false));
  }, [credential]);
  function reload() {
    return api<Workspace[]>("/workspaces").then(setWorkspaces);
  }
  useEffect(() => {
    if (!auth) return;
    let alive = true;
    const controller = new AbortController();
    const load = () =>
      Promise.all([
        api<Workspace[]>(
          "/workspaces",
          undefined,
          undefined,
          controller.signal,
        ),
        api<Diagnostics>(
          "/diagnostics",
          undefined,
          undefined,
          controller.signal,
        ),
      ])
        .then(([w, d]) => {
          if (alive) {
            setWorkspaces(w);
            setDiagnostics(d);
          }
        })
        .catch((e) => {
          if (alive) setError(message(e));
        });
    void load();
    const timer = setInterval(load, 5000);
    return () => {
      alive = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [auth]);
  async function logout() {
    await api("/auth/logout", {});
    setAuth(false);
    setSelected(null);
    setWorkspaces([]);
    setCsrf("");
    connect("");
  }
  return {
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
  };
}
