import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type Session } from "../stt/api";
import { reasonMessage } from "./api";
import {
  createMeetingPoller,
  MeetingJobPages,
  verifiedCards,
  type MeetingJob,
  type MeetingJobsSnapshot,
  type MeetingSubscription,
} from "./jobs";
export type { MeetingCard } from "./jobs";

const emptySubscription: MeetingSubscription = {
  enabled: false,
  workspace_id: null,
  revision_id: null,
};
export function useMeetingAssistant({
  session,
  workspaceId,
  revisionId,
  onRestore,
  visible = true,
}: {
  session: Session | null;
  workspaceId: string;
  revisionId: string | null;
  onRestore: (workspaceId: string) => void;
  visible?: boolean;
}) {
  const [subscription, setSubscription] = useState(emptySubscription);
  const [snapshot, setSnapshot] = useState<MeetingJobsSnapshot | null>(null);
  const [error, setError] = useState("");
  const [restoring, setRestoring] = useState(false);
  const [mutating, setMutating] = useState(false);
  const [retryingId, setRetryingId] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<string[]>([]);
  const [reload, setReload] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const pages = useRef(new MeetingJobPages());
  const activePoller = useRef<ReturnType<
    typeof createMeetingPoller<MeetingJobsSnapshot>
  > | null>(null);
  const sessionId = session?.id ?? "";
  const currentSession = useRef(sessionId);
  currentSession.current = sessionId;
  const pendingStart = useRef<MeetingSubscription | null>(null);
  const restore = useRef(onRestore);
  restore.current = onRestore;
  useEffect(() => {
    setSnapshot(null);
    setDismissed([]);
    setError("");
    setSubscription(pendingStart.current ?? emptySubscription);
    if (!sessionId) return;
    let alive = true;
    const controller = new AbortController();
    const requested = pendingStart.current;
    pendingStart.current = null;
    setRestoring(true);
    api<MeetingSubscription>(
      `/meeting/sessions/${encodeURIComponent(sessionId)}/subscription`,
      {
        signal: controller.signal,
        ...(requested
          ? { method: "PUT", body: JSON.stringify(requested) }
          : {}),
      },
    )
      .then((value) => {
        if (!alive) return;
        setSubscription(value);
        if (value.workspace_id) restore.current(value.workspace_id);
      })
      .catch((caught) => {
        if (alive)
          setError(
            reasonMessage(
              String(caught instanceof Error ? caught.message : caught),
            ),
          );
      })
      .finally(() => {
        if (alive) setRestoring(false);
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [sessionId]);

  useEffect(() => {
    setSnapshot(null);
    pages.current = new MeetingJobPages();
    setLoadingMore(false);
  }, [workspaceId, sessionId]);

  useEffect(() => {
    if (!sessionId || !workspaceId || restoring || !visible) return;
    const poller = createMeetingPoller({
      read: (signal) =>
        pages.current.read(
          (cursor, pageSignal) =>
            api<MeetingJobsSnapshot>(
              `/meeting/sessions/${encodeURIComponent(sessionId)}/jobs?workspace_id=${encodeURIComponent(workspaceId)}&limit=15${cursor ? `&cursor=${encodeURIComponent(cursor)}&include_anchor=true` : ""}`,
              { signal: pageSignal },
            ),
          signal,
        ),
      visible: () => document.visibilityState !== "hidden",
      receive: (value) => {
        setSnapshot(value);
        setLoadingMore(pages.current.pending);
        setError("");
      },
      fail: (caught) => {
        setLoadingMore(false);
        setError(
          reasonMessage(
            String(caught instanceof Error ? caught.message : caught),
          ),
        );
      },
    });
    activePoller.current = poller;
    const onVisibility = () => {
      void poller.tick();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      poller.stop();
      if (activePoller.current === poller) activePoller.current = null;
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [sessionId, workspaceId, restoring, reload, visible]);

  const loadMore = useCallback(() => {
    if (pages.current.pending || pages.current.loadMore()) {
      setLoadingMore(true);
      void activePoller.current?.tick();
    }
  }, []);

  const setEnabled = useCallback(
    async (enabled: boolean) => {
      const value: MeetingSubscription = {
        enabled,
        workspace_id: workspaceId,
        revision_id: revisionId,
      };
      if (!sessionId) {
        pendingStart.current = enabled ? value : null;
        setSubscription(value);
        return;
      }
      setMutating(true);
      try {
        const saved = await api<MeetingSubscription>(
          `/meeting/sessions/${encodeURIComponent(sessionId)}/subscription`,
          { method: "PUT", body: JSON.stringify(value) },
        );
        if (currentSession.current === sessionId) {
          setSubscription(saved);
          setError("");
          setReload((v) => v + 1);
        }
      } finally {
        setMutating(false);
      }
    },
    [sessionId, workspaceId, revisionId],
  );
  const retry = useCallback(
    async (job: MeetingJob) => {
      setRetryingId(job.id);
      try {
        await api(
          `/meeting/sessions/${encodeURIComponent(sessionId)}/jobs/${encodeURIComponent(job.id)}/retry`,
          {
            method: "POST",
            body: JSON.stringify({ workspace_id: workspaceId }),
          },
        );
        if (currentSession.current === sessionId) {
          setError("");
          setReload((v) => v + 1);
        }
      } catch (caught) {
        if (currentSession.current === sessionId)
          setError(
            reasonMessage(
              String(caught instanceof Error ? caught.message : caught),
            ),
          );
      } finally {
        setRetryingId(null);
      }
    },
    [sessionId, workspaceId],
  );
  const cards = useMemo(
    () =>
      verifiedCards(
        snapshot?.jobs ?? [],
        session,
        workspaceId,
        revisionId,
      ).filter((card) => !dismissed.includes(card.result.popup!.id)),
    [snapshot, session, workspaceId, revisionId, dismissed],
  );
  const dismiss = useCallback(
    (id: string) => setDismissed((current) => [...current, id]),
    [],
  );
  return {
    cards,
    loadMore,
    loadingMore,
    jobs: snapshot?.jobs ?? [],
    snapshot,
    error,
    enabled: subscription.enabled && subscription.workspace_id === workspaceId,
    subscription,
    restoring,
    mutating,
    retryingId,
    setEnabled,
    retry,
    dismiss,
  };
}
