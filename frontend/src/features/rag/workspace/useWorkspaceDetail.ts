import { useEffect, useRef, useState } from "react";
import {
  api,
  belongsTo,
  RagApiError,
  type Evidence,
  type Job,
  type Revision,
  type SearchResult,
  type Workspace,
} from "../api";
import { message } from "../utils";
import { useWorkspace } from "../../../workspace/context";
import type { HistoryDetail } from "../history/types";
import {
  readResume,
  rememberQuestion as rememberWorkspaceQuestion,
} from "../history/resume";
import { rememberQuestion } from "../history/bookmark";
import { useOnboarding } from "../../onboarding/context";
import { questionPending } from "../history/QuestionProgress";

export function useWorkspaceDetail({
  initial,
  initialResult,
  onError,
  onRefresh,
  onDeleted,
}: {
  initial: Workspace;
  initialResult?: SearchResult;
  onError: (message: string) => void;
  onRefresh: () => Promise<unknown>;
  onDeleted: () => void;
}) {
  const { access } = useWorkspace();
  const onboarding = useOnboarding();
  const onboardingRequest = onboarding?.request;
  const accountId = access.account?.id;
  const resumeCancelled = useRef(false);
  const submission = useRef<{ signature: string; key: string } | null>(null);
  const [ws, setWs] = useState(initial),
    [tab, setTab] = useState("search"),
    [query, setQuery] = useState(initialResult?.query || ""),
    [result, setResult] = useState<SearchResult | null>(initialResult || null),
    [searchAction, setSearchAction] = useState<"search" | "answer" | null>(
      null,
    ),
    [revisions, setRevisions] = useState<Revision[]>([]),
    [revision, setRevision] = useState(initialResult?.revision_id || ""),
    [history, setHistory] = useState<SearchResult[]>([]),
    [evidence, setEvidence] = useState<Evidence | null>(null),
    [confirmDelete, setConfirmDelete] = useState(false),
    [proxy, setProxy] = useState(""),
    [refreshing, setRefreshing] = useState(false);
  const controller = useRef(new AbortController()),
    serial = useRef(0);
  useEffect(() => {
    if (
      !onboardingRequest ||
      onboardingRequest.type === "create" ||
      onboardingRequest.workspaceId !== initial.id ||
      !onboardingRequest.query
    )
      return;
    resumeCancelled.current = true;
    serial.current++;
    setQuery(onboardingRequest.query);
    setResult(null);
    setRevision("");
    setEvidence(null);
    setSearchAction(null);
  }, [initial.id, onboardingRequest?.id]);
  useEffect(() => {
    if (initialResult) {
      rememberWorkspaceQuestion(
        accountId,
        initial.id,
        initialResult.request_id,
      );
      return;
    }
    const saved = readResume(accountId);
    if (saved?.workspaceId !== initial.id || !saved.questionId) return;
    const c = new AbortController();
    const seq = serial.current;
    const scope =
      access.role === "admin" || access.role === "superadmin" ? "all" : "mine";
    void api<HistoryDetail>(
      `/history/${saved.questionId}?scope=${scope}`,
      undefined,
      undefined,
      c.signal,
    )
      .then(({ result: restored }) => {
        if (
          c.signal.aborted ||
          seq !== serial.current ||
          resumeCancelled.current
        )
          return;
        if (!belongsTo(initial.id, restored)) return;
        setResult(restored);
        setQuery(restored.query);
        setRevision(restored.revision_id || "");
      })
      .catch((error) => {
        if (
          c.signal.aborted ||
          seq !== serial.current ||
          resumeCancelled.current
        )
          return;
        if (
          error instanceof RagApiError &&
          ["NOT_FOUND", "FORBIDDEN"].includes(error.code)
        ) {
          rememberWorkspaceQuestion(accountId, initial.id, null);
        } else onError(message(error));
      });
    return () => c.abort();
  }, [initial.id, accountId]);
  const pendingQuestion = questionPending(result?.status);
  const questionId = result?.request_id;
  useEffect(() => {
    if (!pendingQuestion || !questionId) return;
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const scope =
      access.role === "admin" || access.role === "superadmin" ? "all" : "mine";
    const poll = async () => {
      try {
        const { result: updated } = await api<HistoryDetail>(
          `/history/${questionId}?scope=${scope}`,
          undefined,
          undefined,
          c.signal,
        );
        if (c.signal.aborted) return;
        setResult((previous) =>
          previous?.request_id === questionId ? updated : previous,
        );
        setHistory((previous) =>
          previous.map((item) =>
            item.request_id === questionId ? updated : item,
          ),
        );
        if (!questionPending(updated.status)) return;
      } catch (error) {
        if (c.signal.aborted) return;
        if (
          error instanceof RagApiError &&
          [401, 403, 404].includes(error.status)
        ) {
          onError(message(error));
          setResult((previous) =>
            previous?.request_id === questionId ? null : previous,
          );
          return;
        }
        // A brief outage stops only polling; the accepted job remains on the server.
      }
      timer = setTimeout(() => void poll(), 2000);
    };
    void poll();
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [questionId, pendingQuestion, initial.id, accountId, access.role]);
  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    let pending = false;
    const load = () => {
      if (pending) return;
      pending = true;
      Promise.all([
        api<Workspace>(`/workspaces/${ws.id}`, undefined, undefined, c.signal),
        api<Revision[]>(
          `/workspaces/${ws.id}/revisions`,
          undefined,
          undefined,
          c.signal,
        ),
        api<SearchResult[]>(
          `/workspaces/${ws.id}/questions`,
          undefined,
          undefined,
          c.signal,
        ),
      ])
        .then(([w, r, h]) => {
          if (!c.signal.aborted) {
            setWs(w);
            setRevisions(r);
            setHistory(h);
          }
        })
        .catch((e) => {
          if (!c.signal.aborted) onError(message(e));
        })
        .finally(() => (pending = false));
    };
    load();
    const timer = setInterval(load, 4000);
    return () => {
      c.abort();
      clearInterval(timer);
      serial.current++;
    };
  }, [initial.id, accountId]);
  async function search(answer = false, approvalProviderId?: string) {
    if (searchAction !== null) return;
    resumeCancelled.current = true;
    const seq = ++serial.current;
    onError("");
    setSearchAction(answer ? "answer" : "search");
    setResult(null);
    setEvidence(null);
    try {
      if (approvalProviderId) {
        const approved = await api<Workspace>(
          `/workspaces/${ws.id}`,
          { external_llm_approved: true, provider_id: approvalProviderId },
          "PATCH",
          controller.current.signal,
        );
        if (seq !== serial.current || controller.current.signal.aborted) return;
        setWs(approved);
        void onRefresh().catch((error) => onError(message(error)));
      }
      const body = { query, revision_id: revision || null };
      const signature = JSON.stringify([accountId, ws.id, body]);
      if (answer && submission.current?.signature !== signature)
        submission.current = { signature, key: crypto.randomUUID() };
      const r = await api<SearchResult>(
        `/workspaces/${ws.id}/${answer ? "questions" : "search"}`,
        body,
        "POST",
        controller.current.signal,
        answer && submission.current
          ? { "Idempotency-Key": submission.current.key }
          : undefined,
      );
      if (answer) submission.current = null;
      if (
        seq === serial.current &&
        belongsTo(ws.id, r) &&
        !controller.current.signal.aborted
      ) {
        setResult(r);
        onboarding?.reportSearch(ws.id);
        rememberWorkspaceQuestion(accountId, ws.id, r.request_id);
        rememberQuestion(access.account?.id, "mine", r.request_id);
        setHistory((previous) => [
          r,
          ...previous.filter((h) => h.request_id !== r.request_id),
        ]);
      }
    } catch (e) {
      if (!controller.current.signal.aborted) onError(message(e));
    } finally {
      if (seq === serial.current) setSearchAction(null);
    }
  }
  async function refresh(allowReview = false) {
    if (refreshing) return;
    setRefreshing(true);
    onError("");
    try {
      const j = await api<Job>(`/workspaces/${ws.id}/index-jobs`, {
        allow_review: allowReview,
      });
      setWs((previous) => ({ ...previous, latest_job: j }));
      await onRefresh();
    } catch (e) {
      onError(message(e));
    } finally {
      setRefreshing(false);
    }
  }
  function selectRevision(value: string) {
    serial.current++;
    setRevision(value);
    setResult(null);
    setEvidence(null);
    setSearchAction(null);
    rememberWorkspaceQuestion(accountId, ws.id, null);
  }
  function selectHistory(entry: SearchResult) {
    serial.current++;
    setSearchAction(null);
    setResult(entry);
    setRevision(entry.revision_id || "");
    setQuery(entry.query);
    setEvidence(null);
    rememberWorkspaceQuestion(accountId, ws.id, entry.request_id);
    rememberQuestion(access.account?.id, "mine", entry.request_id);
  }
  async function openDocument(path: string, revisionId?: string) {
    try {
      const params = new URLSearchParams({
        relative_path: path,
        metadata_only: "true",
      });
      if (revisionId) params.set("revision_id", revisionId);
      const result = await api<{ evidence: Evidence }>(
        `/workspaces/${ws.id}/documents?${params}`,
        undefined,
        undefined,
        controller.current.signal,
      );
      if (!controller.current.signal.aborted) setEvidence(result.evidence);
    } catch (error) {
      if (controller.current.signal.aborted) return;
      if (
        error instanceof RagApiError &&
        ["NOT_FOUND", "REVISION_NOT_READY"].includes(error.code)
      ) {
        setEvidence({
          workspace_id: ws.id,
          revision_id: "source",
          evidence_id: `source:${path}`,
          relative_path: path,
          source_preview: true,
          text: "",
          title_path: [],
          location: { type: "source" },
        });
      } else onError(message(error));
    }
  }
  async function updateConsent(approved: boolean, providerId?: string) {
    try {
      setWs(
        await api<Workspace>(
          `/workspaces/${ws.id}`,
          {
            external_llm_approved: approved,
            provider_id: providerId,
          },
          "PATCH",
        ),
      );
    } catch (error) {
      onError(message(error));
    }
  }
  async function checkConnection() {
    setProxy("연결 확인 중…");
    try {
      setProxy(
        JSON.stringify(await api("/diagnostics/llm-check", {}), null, 2),
      );
    } catch (error) {
      setProxy(message(error));
    }
  }
  async function deleteWorkspace() {
    try {
      await api(`/workspaces/${ws.id}`, undefined, "DELETE");
      onDeleted();
    } catch (error) {
      onError(message(error));
    }
  }
  async function cancelJob() {
    const job = ws.latest_job;
    if (!job) return;
    try {
      await api(`/workspaces/${ws.id}/index-jobs/${job.job_id}/cancel`, {});
    } catch (error) {
      onError(message(error));
    }
  }
  return {
    ws,
    tab,
    query,
    result,
    searching: searchAction !== null,
    searchAction,
    revisions,
    revision,
    history,
    evidence,
    confirmDelete,
    proxy,
    setTab,
    setQuery: (value: string) => {
      resumeCancelled.current = true;
      setQuery(value);
    },
    setEvidence,
    openDocument,
    setConfirmDelete,
    search,
    refresh,
    refreshing,
    selectRevision,
    selectHistory,
    updateConsent,
    checkConnection,
    deleteWorkspace,
    cancelJob,
  };
}
export type WorkspaceDetail = ReturnType<typeof useWorkspaceDetail>;
