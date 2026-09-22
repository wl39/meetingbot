import { CheckCircle2, Loader2, X } from "lucide-react";
import type { InstallJob } from "../api";
import { isRunningJob } from "../format";
export default function JobList({ jobs }: { jobs: InstallJob[] }) {
  if (!jobs.length)
    return (
      <p className="management-muted">
        아직 설치·적용 기록이 없습니다. 필요한 모델을 음성 인식 화면에서
        설치하세요.
      </p>
    );
  return (
    <div className="management-jobs">
      {jobs
        .slice()
        .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
        .slice(0, 12)
        .map((job) => (
          <div className={`management-job ${job.status}`} key={job.id}>
            <span className="management-job-icon">
              {isRunningJob(job) ? (
                <Loader2 className="management-spin" size={20} />
              ) : job.status === "completed" ? (
                <CheckCircle2 size={20} />
              ) : (
                <X size={20} />
              )}
            </span>
            <div>
              <strong>
                {job.message ||
                  (job.action === "install" ? "모델 설치" : "모델 적용")}
              </strong>
              <small>
                {
                  {
                    queued: "대기 중",
                    running: "진행 중",
                    completed: "완료",
                    failed: "실패 · 다시 시도할 수 있습니다",
                  }[job.status]
                }{" "}
                · {new Date(job.created_at).toLocaleString("ko-KR")}
              </small>
              {isRunningJob(job) && (
                <progress
                  aria-label="설치 진행률"
                  max={100}
                  value={job.progress == null ? undefined : job.progress}
                />
              )}
              {job.status === "failed" && (
                <p>
                  설치를 완료하지 못했습니다. 연결과 저장 공간을 확인한 뒤 같은
                  모델의 설치 또는 적용을 다시 시도하세요.
                </p>
              )}
            </div>
          </div>
        ))}
    </div>
  );
}
