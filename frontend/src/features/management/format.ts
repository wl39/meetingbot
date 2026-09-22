import type { InstallJob } from "./api";

export const isRunningJob = (job: InstallJob) =>
  ["queued", "running"].includes(job.status);
export const engineName = (id?: string) =>
  id === "mlx"
    ? "MLX Whisper"
    : id === "faster-whisper"
      ? "Faster Whisper"
      : "확인 중";
export const modelName = (id?: string) =>
  id === "small"
    ? "Whisper Small"
    : id === "large-v3-turbo"
      ? "Whisper Large v3 Turbo"
      : "확인 중";
export const bytes = (n: number) => `${(n / 1024 ** 3).toFixed(1)} GB`;
