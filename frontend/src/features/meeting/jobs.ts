import type { Session } from "../stt/api";
import type { MeetingResult } from "./api";

export type MeetingPolicy = {
  version: number;
  priority_response_target_seconds: number;
  pressure_ratio: number;
  protect_ratio: number;
  recovery_ratio: number;
  recovery_seconds: number;
  context_wait_seconds: number;
  filter_model: string;
  filter_timeout_seconds: number;
  generation_timeout_seconds: number;
  scope_profile: {
    description: string;
    included_topics: string[];
    excluded_topics: string[];
    aliases: string[];
  };
};
export type MeetingSubscription = {
  enabled: boolean;
  workspace_id: string | null;
  revision_id: string | null;
};
export type MeetingJob = {
  id: string;
  session_id: string;
  utterance_id: string;
  utterance_revision: number;
  source_key: string;
  text: string;
  score: number | null;
  classification: {
    reason?: string;
    reason_code?: string;
    scope?: string;
    query?: string;
    [key: string]: unknown;
  } | null;
  queue_class: "PQ" | "SQ" | null;
  state:
    | "CLASSIFYING"
    | "AWAITING_CONTEXT"
    | "QUEUED"
    | "RUNNING"
    | "PAUSED"
    | "RETRY_WAIT"
    | "COMPLETED"
    | "FAILED"
    | "CANCELLED"
    | "SUPERSEDED";
  stage: string;
  deadline_at: number | null;
  deadline_missed: boolean;
  reason: string | null;
  result: MeetingResult | null;
  created_at: number;
  updated_at: number;
  origin: "live" | "file";
};
export type MeetingJobsSnapshot = {
  jobs: MeetingJob[];
  next_cursor: string | null;
  total: number;
  scheduler: {
    mode: "NORMAL" | "PRESSURED" | "PQ_ONLY" | "RECOVERY";
    pq_pending: number;
    sq_pending: number;
    filter_pending: number;
    oldest_sq_seconds: number;
  };
  policy: MeetingPolicy;
};
export type MeetingCard = {
  result: MeetingResult;
  sourceKey: string;
  quote: string;
};
export const schedulerLabels: Record<
  MeetingJobsSnapshot["scheduler"]["mode"],
  string
> = {
  NORMAL: "일반 처리",
  PRESSURED: "우선큐 처리 강화",
  PQ_ONLY: "우선큐 집중 · 보조큐 일시정지",
  RECOVERY: "보조큐 처리 재개",
};
export const scoreLabels: Record<number, string> = {
  1: "추임새 · 기록 보존",
  2: "일상·범위 밖 · 기록 보존",
  3: "업무 주제 · 보조큐",
  4: "업무 설명·질문 · 우선큐",
  5: "AI 직접 요청 · 우선큐",
};
export function jobStatus(job: MeetingJob): string {
  if (job.result?.status === "needs_clarification")
    return "업무 대상 확인 필요";
  if (job.result?.status === "unsupported_action")
    return "직접 실행할 수 없는 요청";
  if (job.state === "COMPLETED" && job.score !== null && job.score <= 2)
    return "원문·분류 저장 완료";
  if (
    job.state === "COMPLETED" &&
    job.result?.status === "insufficient_evidence"
  )
    return "검토 완료 · 문서 근거 부족";
  if (job.state === "COMPLETED" && job.result?.status === "suppressed")
    return "검토 완료 · 추가 안내 없음";
  return {
    CLASSIFYING: "발화 중요도 판단 중",
    AWAITING_CONTEXT: "분류 보류 · 업무 대상을 확인해 주세요",
    QUEUED: "처리 대기",
    RUNNING: "문서 검토 중",
    PAUSED: "우선큐 처리 후 재개",
    RETRY_WAIT: "잠시 후 자동 재시도",
    COMPLETED: "검토 완료",
    FAILED: "검토 실패 · 재시도 가능",
    CANCELLED: "검토 종료",
    SUPERSEDED: "수정된 발화·문맥으로 대체됨",
  }[job.state];
}
export function deadlineLabel(
  job: MeetingJob,
  nowSeconds: number,
): string | null {
  if (job.queue_class !== "PQ" || job.deadline_at === null) return null;
  if (job.deadline_missed) return "응답 목표시간 초과";
  if (["COMPLETED", "FAILED", "CANCELLED", "SUPERSEDED"].includes(job.state))
    return null;
  const remaining = Math.ceil(job.deadline_at - nowSeconds);
  return remaining > 0
    ? `응답 목표까지 ${remaining}초`
    : "응답 목표시간 경과 · 상태 확인 중";
}
export function verifiedCards(
  jobs: MeetingJob[],
  session: Session | null,
  workspaceId: string,
  revisionId: string | null,
): MeetingCard[] {
  if (!session || !revisionId) return [];
  return [...jobs]
    .sort((a, b) => b.updated_at - a.updated_at)
    .flatMap((job) => {
      const result = job.result;
      const utterance = session.utterances.find(
        (u) => u.utterance_id === job.utterance_id,
      );
      if (
        job.state !== "COMPLETED" ||
        !utterance ||
        ["partial", "retracted"].includes(utterance.status) ||
        utterance.text !== job.text ||
        !result?.popup ||
        result.status !== "popup" ||
        job.session_id !== session.id ||
        result.session_id !== session.id ||
        result.workspace_id !== workspaceId ||
        result.revision_id !== revisionId ||
        result.utterance_id !== job.utterance_id ||
        !result.popup.citations.length ||
        !result.popup.citations.every((id) =>
          result.evidence.some(
            (e) =>
              e.evidence_id === id &&
              e.workspace_id === workspaceId &&
              e.revision_id === revisionId,
          ),
        )
      )
        return [];
      return [{ result, sourceKey: job.source_key, quote: job.text }];
    });
}

/** Polling owns display refresh only. Stopping it never changes server jobs or subscriptions. */
export function createMeetingPoller<T>({
  read,
  visible,
  receive,
  fail,
}: {
  read: (signal: AbortSignal) => Promise<T>;
  visible: () => boolean;
  receive: (snapshot: T) => void;
  fail: (error: unknown) => void;
}) {
  let disposed = false;
  let active: AbortController | null = null;
  async function tick() {
    if (disposed || active || !visible()) return;
    const controller = new AbortController();
    active = controller;
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const snapshot = await read(controller.signal);
      if (!disposed) receive(snapshot);
    } catch (error) {
      if (!disposed) fail(error);
    } finally {
      clearTimeout(timeout);
      if (active === controller) active = null;
    }
  }
  const timer = setInterval(() => void tick(), 1000);
  void tick();
  return {
    tick,
    stop: () => {
      disposed = true;
      clearInterval(timer);
      active?.abort();
    },
  };
}

/** Poll the live head and at most one opened archive page per tick. */
export class MeetingJobPages {
  private cursors: string[] = [];
  private cache = new Map<string, MeetingJobsSnapshot>();
  private first: MeetingJobsSnapshot | null = null;
  private last: MeetingJobsSnapshot | null = null;
  private refreshIndex = 0;
  get pending() {
    return this.cursors.some((cursor) => !this.cache.has(cursor));
  }
  loadMore(): boolean {
    const next = this.last?.next_cursor;
    if (!next || this.pending || this.cursors.includes(next)) return false;
    // Preserve the page the user already opened while the live head moves.
    const head = this.first?.jobs[0]?.id;
    if (head && this.first && !this.cursors.includes(head)) {
      this.cursors.push(head);
      this.cache.set(head, this.first);
    }
    if (!this.cursors.includes(next)) this.cursors.push(next);
    return true;
  }
  async read(
    readPage: (
      cursor: string | null,
      signal: AbortSignal,
    ) => Promise<MeetingJobsSnapshot>,
    signal: AbortSignal,
  ): Promise<MeetingJobsSnapshot> {
    const first = await readPage(null, signal);
    const pending = this.cursors.find((cursor) => !this.cache.has(cursor));
    const cursor =
      pending ??
      (this.cursors.length
        ? this.cursors[this.refreshIndex % this.cursors.length]
        : null);
    if (cursor) {
      signal.throwIfAborted();
      const archive = await readPage(cursor, signal);
      signal.throwIfAborted();
      this.cache.set(cursor, archive);
      if (!pending)
        this.refreshIndex = (this.refreshIndex + 1) % this.cursors.length;
    }
    const pages = [
      first,
      ...this.cursors.flatMap((key) =>
        this.cache.has(key) ? [this.cache.get(key)!] : [],
      ),
    ];
    const jobs = new Map<string, MeetingJob>();
    for (const page of pages)
      for (const job of page.jobs) {
        const prior = jobs.get(job.id);
        if (!prior || job.updated_at >= prior.updated_at) jobs.set(job.id, job);
      }
    const next =
      jobs.size >= first.total
        ? null
        : (pages
            .map((page) => page.next_cursor)
            .find(
              (value) =>
                value &&
                !this.cursors.includes(value) &&
                !pages.some((page) => {
                  const index = page.jobs.findIndex((job) => job.id === value);
                  return index >= 0 && index < page.jobs.length - 1;
                }),
            ) ?? null);
    const snapshot = {
      ...first,
      jobs: [...jobs.values()].sort(
        (a, b) => b.created_at - a.created_at || b.id.localeCompare(a.id),
      ),
      next_cursor: next,
    };
    signal.throwIfAborted();
    this.first = first;
    this.last = snapshot;
    return snapshot;
  }
}
