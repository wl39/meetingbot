import type { Job } from "./api";
export const busy = (job: Job | null) =>
  !!job && ["QUEUED", "RUNNING"].includes(job.state);
export const short = (id?: string | null) => (id ? id.slice(0, 8) : "—");
export const time = (stamp: number) =>
  new Date(stamp * 1000).toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
export const message = (error: unknown) =>
  error instanceof Error ? error.message : String(error);
