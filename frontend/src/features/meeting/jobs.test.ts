import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session } from "../stt/api";
import type { Evidence } from "../rag/api";
import {
  createMeetingPoller,
  MeetingJobPages,
  type MeetingJobsSnapshot,
  deadlineLabel,
  jobStatus,
  verifiedCards,
  type MeetingJob,
  type MeetingPolicy,
} from "./jobs";
import { policyError, policyList } from "./MeetingPolicyPanel";

const makeJob = (patch: Partial<MeetingJob> = {}): MeetingJob => ({
  id: "job-a",
  session_id: "session",
  utterance_id: "a",
  utterance_revision: 1,
  source_key: "server-key",
  text: "운영 로그는 45일이에요",
  score: 4,
  classification: null,
  queue_class: "PQ",
  state: "COMPLETED",
  stage: "done",
  deadline_at: 120,
  deadline_missed: false,
  reason: null,
  created_at: 100,
  updated_at: 105,
  origin: "live",
  result: {
    workspace_id: "workspace",
    session_id: "session",
    utterance_id: "a",
    utterance_revision: 1,
    revision_id: "docs-v1",
    request_id: "req",
    status: "popup",
    popup: {
      id: "popup",
      kind: "info",
      color: "blue",
      title: "로그 보관",
      message: "확인 결과",
      confidence: 0.9,
      citations: ["source"],
    },
    evidence: [
      {
        evidence_id: "source",
        workspace_id: "workspace",
        revision_id: "docs-v1",
      } as Evidence,
    ],
    timings_ms: {},
  },
  ...patch,
});
const session = {
  id: "session",
  mode: "file",
  utterances: [
    {
      utterance_id: "a",
      revision: 1,
      text: "운영 로그는 45일이에요",
      status: "final",
    },
  ],
} as Session;
const policy: MeetingPolicy = {
  version: 2,
  priority_response_target_seconds: 20,
  pressure_ratio: 0.5,
  protect_ratio: 0.8,
  recovery_ratio: 0.4,
  recovery_seconds: 3,
  context_wait_seconds: 2,
  filter_model: "",
  filter_timeout_seconds: 8,
  generation_timeout_seconds: 20,
  scope_profile: {
    description: "우리 서버",
    included_topics: ["로그"],
    excluded_topics: ["개인 프로젝트"],
    aliases: [],
  },
};

describe("server meeting result presentation", () => {
  it("preserves filler and social speech as recorded outcomes, and shows clarification separately", () => {
    expect(
      jobStatus(makeJob({ score: 1, queue_class: null, result: null })),
    ).toBe("원문·분류 저장 완료");
    expect(
      jobStatus(makeJob({ score: 2, queue_class: null, result: null })),
    ).toBe("원문·분류 저장 완료");
    expect(
      jobStatus(
        makeJob({ score: null, state: "AWAITING_CONTEXT", queue_class: null }),
      ),
    ).toContain("분류 보류");
    expect(
      jobStatus(makeJob({ score: 3, state: "PAUSED", queue_class: "SQ" })),
    ).toContain("재개");
  });
  it("keeps a missed deadline visible after late completion and does not label a pending result as success", () => {
    expect(deadlineLabel(makeJob({ deadline_missed: true }), 150)).toBe(
      "응답 목표시간 초과",
    );
    expect(deadlineLabel(makeJob({ state: "RUNNING" }), 119)).toBe(
      "응답 목표까지 1초",
    );
    expect(deadlineLabel(makeJob({ state: "RUNNING" }), 125)).toContain(
      "상태 확인 중",
    );
    expect(deadlineLabel(makeJob({ queue_class: "SQ" }), 150)).toBeNull();
  });
  it("shows file results with verified matching evidence, without a browser queue or 12-result truncation", () => {
    const jobs = Array.from({ length: 20 }, (_, i) =>
      makeJob({ id: String(i), origin: "file" }),
    );
    expect(verifiedCards(jobs, session, "workspace", "docs-v1")).toHaveLength(
      20,
    );
  });
  it("rejects superseded jobs, changed transcripts, wrong workspace/revision and ungrounded popups", () => {
    expect(
      verifiedCards(
        [makeJob({ state: "SUPERSEDED" })],
        session,
        "workspace",
        "docs-v1",
      ),
    ).toEqual([]);
    expect(
      verifiedCards(
        [makeJob({ text: "운영 로그는 90일이에요" })],
        session,
        "workspace",
        "docs-v1",
      ),
    ).toEqual([]);
    expect(verifiedCards([makeJob()], session, "other", "docs-v1")).toEqual([]);
    expect(verifiedCards([makeJob()], session, "workspace", "docs-v2")).toEqual(
      [],
    );
    const missingEvidence = makeJob();
    missingEvidence.result!.evidence = [];
    expect(
      verifiedCards([missingEvidence], session, "workspace", "docs-v1"),
    ).toEqual([]);
    const wrongSource = makeJob();
    wrongSource.result!.evidence[0].workspace_id = "other";
    expect(
      verifiedCards([wrongSource], session, "workspace", "docs-v1"),
    ).toEqual([]);
  });
});
describe("meeting server polling lifecycle", () => {
  afterEach(() => vi.useRealTimers());
  it("does not overlap slow fetches, pauses reads when hidden, and resumes on visibility", async () => {
    vi.useFakeTimers();
    let visible = true;
    let resolve!: (value: number) => void;
    const read = vi.fn(
      () =>
        new Promise<number>((done) => {
          resolve = done;
        }),
    );
    const receive = vi.fn();
    const poller = createMeetingPoller({
      read,
      visible: () => visible,
      receive,
      fail: vi.fn(),
    });
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3000);
    expect(read).toHaveBeenCalledTimes(1);
    resolve(1);
    await Promise.resolve();
    expect(receive).toHaveBeenCalledWith(1);
    visible = false;
    await vi.advanceTimersByTimeAsync(5000);
    expect(read).toHaveBeenCalledTimes(1);
    visible = true;
    void poller.tick();
    expect(read).toHaveBeenCalledTimes(2);
    poller.stop();
  });
  it("unmount aborts only the display fetch and prevents late results or subsequent reads", async () => {
    vi.useFakeTimers();
    let signal!: AbortSignal;
    let resolve!: (value: number) => void;
    const read = vi.fn((value: AbortSignal) => {
      signal = value;
      return new Promise<number>((done) => {
        resolve = done;
      });
    });
    const receive = vi.fn();
    const fail = vi.fn();
    const poller = createMeetingPoller({
      read,
      visible: () => true,
      receive,
      fail,
    });
    poller.stop();
    expect(signal.aborted).toBe(true);
    resolve(1);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(20000);
    expect(receive).not.toHaveBeenCalled();
    expect(fail).not.toHaveBeenCalled();
    expect(read).toHaveBeenCalledTimes(1);
  });
});
describe("admin meeting policy validation", () => {
  it("accepts the default policy and rejects unsafe or inconsistent timing inputs", () => {
    expect(policyError(policy)).toBe("");
    expect(
      policyError({ ...policy, priority_response_target_seconds: 0 }),
    ).not.toBe("");
    expect(policyError({ ...policy, pressure_ratio: 0.9 })).not.toBe("");
    expect(policyError({ ...policy, recovery_ratio: 0.6 })).not.toBe("");
    expect(policyError({ ...policy, filter_timeout_seconds: NaN })).not.toBe(
      "",
    );
    expect(policyError({ ...policy, context_wait_seconds: 0 })).toBe("");
    expect(policyError({ ...policy, recovery_seconds: 0 })).toBe("");
    expect(
      policyError({ ...policy, priority_response_target_seconds: 121 }),
    ).not.toBe("");
    expect(
      policyError({ ...policy, priority_response_target_seconds: 3.5 }),
    ).not.toBe("");
    expect(policyError({ ...policy, filter_timeout_seconds: 16 })).not.toBe("");
    expect(policyError({ ...policy, generation_timeout_seconds: 61 })).not.toBe(
      "",
    );
    expect(policyError({ ...policy, context_wait_seconds: 6 })).not.toBe("");
    expect(policyError({ ...policy, recovery_seconds: 31 })).not.toBe("");
    expect(policyError({ ...policy, protect_ratio: 1 })).not.toBe("");
    expect(
      policyError({
        ...policy,
        scope_profile: {
          ...policy.scope_profile,
          description: "가".repeat(601),
        },
      }),
    ).not.toBe("");
    expect(policyList(" 로그 \n\n Docker \n")).toEqual(["로그", "Docker"]);
  });
});

describe("meeting archive pagination", () => {
  function source() {
    const state = {
      jobs: Array.from({ length: 7 }, (_, i) =>
        makeJob({ id: String(7 - i), created_at: 7 - i, updated_at: 10 }),
      ),
    };
    const reads: (string | null)[] = [];
    const readPage = async (
      cursor: string | null,
    ): Promise<MeetingJobsSnapshot> => {
      reads.push(cursor);
      const index = cursor
        ? state.jobs.findIndex((job) => job.id === cursor) + 1
        : 0;
      const slice = state.jobs.slice(index, index + 2);
      const anchor = cursor
        ? state.jobs.find((job) => job.id === cursor)
        : null;
      return {
        jobs: anchor ? [anchor, ...slice] : slice,
        next_cursor: index + 2 < state.jobs.length ? slice.at(-1)!.id : null,
        total: state.jobs.length,
        scheduler: {
          mode: "NORMAL",
          pq_pending: 0,
          sq_pending: 1,
          filter_pending: 0,
          oldest_sq_seconds: 3,
        },
        policy,
      };
    };
    return { state, reads, readPage };
  }
  it("fetches only the first page initially, then keeps loaded history and anchors refreshed after new arrivals", async () => {
    const { state, reads, readPage } = source();
    const pages = new MeetingJobPages();
    const signal = new AbortController().signal;
    const first = await pages.read(readPage, signal);
    expect(first.jobs.map((job) => job.id)).toEqual(["7", "6"]);
    expect(reads).toEqual([null]);
    expect(pages.loadMore()).toBe(true);
    expect(pages.loadMore()).toBe(false);
    const expanded = await pages.read(readPage, signal);
    expect(expanded.jobs.map((job) => job.id)).toEqual(["7", "6", "5", "4"]);
    expect(expanded.total).toBe(7);
    expect(pages.pending).toBe(false);
    state.jobs.find((job) => job.id === "6")!.state = "PAUSED";
    state.jobs.find((job) => job.id === "6")!.updated_at = 12;
    state.jobs.unshift(
      makeJob({ id: "9", created_at: 9 }),
      makeJob({ id: "8", created_at: 8 }),
    );
    reads.length = 0;
    const refreshed = await pages.read(readPage, signal);
    expect(reads).toEqual([null, "7"]);
    reads.length = 0;
    await pages.read(readPage, signal);
    expect(reads).toEqual([null, "6"]);
    expect(refreshed.jobs.find((job) => job.id === "6")?.state).toBe("PAUSED");
    expect(new Set(refreshed.jobs.map((job) => job.id)).size).toBe(
      refreshed.jobs.length,
    );
    expect(refreshed.jobs.some((job) => job.id === "7")).toBe(true);
    expect(refreshed.total).toBe(9);
  });
  it("can load every archive record without duplicate IDs or silent drops", async () => {
    const { readPage } = source();
    const pages = new MeetingJobPages();
    const signal = new AbortController().signal;
    let snapshot = await pages.read(readPage, signal);
    let attempts = 0;
    while (snapshot.next_cursor && attempts++ < 10) {
      expect(pages.loadMore()).toBe(true);
      snapshot = await pages.read(readPage, signal);
    }
    expect(snapshot.jobs).toHaveLength(7);
    expect(snapshot.next_cursor).toBeNull();
    expect(pages.loadMore()).toBe(false);
  });
  it("fetches pages sequentially and leaves a failed extension pending for the next poll", async () => {
    const { readPage } = source();
    const pages = new MeetingJobPages();
    const signal = new AbortController().signal;
    await pages.read(readPage, signal);
    pages.loadMore();
    await expect(
      pages.read(async (cursor) => {
        if (cursor) throw new Error("offline");
        return readPage(cursor);
      }, signal),
    ).rejects.toThrow("offline");
    expect(pages.pending).toBe(true);
    let active = 0,
      maxActive = 0;
    await pages.read(async (cursor) => {
      active++;
      maxActive = Math.max(maxActive, active);
      await Promise.resolve();
      const result = await readPage(cursor);
      active--;
      return result;
    }, signal);
    expect(maxActive).toBe(1);
    expect(pages.pending).toBe(false);
  });
});
