import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  CircleAlert,
  CircleCheck,
  Info,
  LoaderCircle,
  RefreshCw,
  Sparkles,
  TriangleAlert,
  X,
} from "lucide-react";
import { api, time, type Session } from "../stt/api";
import {
  api as ragApi,
  locationLabel,
  type Diagnostics,
  type Workspace,
} from "../rag/api";
import MarkdownView from "../rag/components/MarkdownView";
import EvidencePreview from "../rag/components/EvidencePreview";
import FilePath from "../rag/components/FilePath";
import { readiness, reasonMessage } from "./api";
import { useMeetingAssistant, type MeetingCard } from "./useMeetingAssistant";
import "./meeting.css";
import { useWorkspace } from "../../workspace/context";
import { useOnboarding } from "../onboarding/context";

const kinds = {
  warning: { label: "문서와 차이 있음", color: "red", Icon: CircleAlert },
  caution: { label: "확인 필요", color: "orange", Icon: TriangleAlert },
  info: { label: "참고 정보", color: "blue", Icon: Info },
  success: { label: "문서와 일치", color: "green", Icon: CircleCheck },
} as const;
type MeetingDiagnostics = Diagnostics & { public_origin?: string | null };

function PopupCard({
  card,
  session,
  dismiss,
}: {
  card: MeetingCard;
  session: Session;
  dismiss: (id: string) => void;
}) {
  const popup = card.result.popup!;
  const concept = kinds[popup.kind];
  if (!concept) return null;
  const u = session.utterances.find(
    (entry) => entry.utterance_id === card.result.utterance_id,
  );
  if (
    !u ||
    ["partial", "retracted"].includes(u.status) ||
    u.text !== card.quote
  )
    return null;
  const speaker = u.speaker_id
    ? session.speakers[u.speaker_id] || u.speaker_id
    : "발언자";
  const cited = card.result.evidence.filter((e) =>
    popup.citations.includes(e.evidence_id),
  );
  return (
    <article
      className={`meeting-popup meeting-${concept.color}`}
      aria-label={`${concept.label}: ${popup.title}`}
    >
      <div className="meeting-popup-top">
        <span>
          <concept.Icon size={16} aria-hidden="true" />
          {concept.label}
        </span>
        <button
          className="meeting-dismiss"
          onClick={() => dismiss(popup.id)}
          aria-label={`${popup.title} 안내 닫기`}
        >
          <X size={15} />
        </button>
      </div>
      <h3>{popup.title}</h3>
      <div className="meeting-popup-message">
        <MarkdownView text={popup.message} compact />
      </div>
      <blockquote>
        <span>
          {speaker} · {time(u.start_ms)}
        </span>
        “{card.quote}”
      </blockquote>
      <details className="meeting-evidence">
        <summary>문서 근거 {cited.length}개 확인</summary>
        {cited.map((e) => (
          <div className="meeting-source" key={e.evidence_id}>
            <FilePath path={e.relative_path} />
            <span>
              {locationLabel(e)}
              {e.title_path.length ? ` · ${e.title_path.join(" / ")}` : ""}
            </span>
            {/\.md$/i.test(e.relative_path) ? (
              <EvidencePreview evidence={e} />
            ) : (
              <p>{e.text}</p>
            )}
          </div>
        ))}
      </details>
    </article>
  );
}

export function MeetingAssistant({ session }: { session: Session | null }) {
  const { navigate, access, view } = useWorkspace();
  const tutorial = useOnboarding();
  const visible = view === "file" || view === "live";
  const managesData = access.role === "admin" || access.role === "superadmin";
  const [activating, setActivating] = useState(false);
  const activation = useRef<AbortController | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [diagnostics, setDiagnostics] = useState<MeetingDiagnostics | null>(
    null,
  );
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => () => activation.current?.abort(), [selected]);
  useEffect(() => {
    if (!visible) return;
    let alive = true;
    let pending = false;
    let controller: AbortController | null = null;
    async function refresh() {
      if (pending || document.visibilityState === "hidden") return;
      pending = true;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 15000);
      try {
        const [workspaceResult, diagnosticResult] = await Promise.allSettled([
          api<Workspace[]>("/meeting/workspaces", {
            signal: controller.signal,
          }),
          api<MeetingDiagnostics>("/meeting/diagnostics", {
            signal: controller.signal,
          }),
        ]);
        if (!alive) return;
        if (workspaceResult.status === "rejected") throw workspaceResult.reason;
        if (diagnosticResult.status === "rejected")
          throw diagnosticResult.reason;
        setWorkspaces(workspaceResult.value);
        setDiagnostics(diagnosticResult.value);
        setSelected((current) =>
          workspaceResult.value.some((w) => w.id === current)
            ? current
            : ((
                workspaceResult.value.find(
                  (w) => !readiness(w, diagnosticResult.value),
                ) ?? workspaceResult.value[0]
              )?.id ?? ""),
        );
        setLoadError("");
      } catch (caught) {
        if (!alive) return;
        setDiagnostics(null);
        setLoadError(
          caught instanceof Error && caught.name === "AbortError"
            ? "자료 연결에 시간이 걸리고 있습니다. 다시 시도해 주세요."
            : reasonMessage(
                String(caught instanceof Error ? caught.message : caught),
              ),
        );
      } finally {
        clearTimeout(timeout);
        pending = false;
        if (alive) setLoading(false);
      }
    }
    setLoading(true);
    void refresh();
    const interval = window.setInterval(refresh, 15000);
    const onVisibility = () => {
      void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      alive = false;
      clearInterval(interval);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [reload, visible]);
  const workspace = workspaces.find((w) => w.id === selected);
  const assistant = useMeetingAssistant({
    session,
    workspaceId: selected,
    revisionId: workspace?.active_revision_id ?? null,
    onRestore: setSelected,
    visible,
  });
  const enabled = assistant.enabled;
  const blocked = readiness(workspace, diagnostics, managesData && !enabled);
  const canStart = !loading && !loadError && !blocked && !assistant.restoring;
  const changing = activating || assistant.mutating || assistant.restoring;
  useEffect(() => {
    if (
      tutorial?.active &&
      tutorial.workspaceId &&
      !enabled &&
      !changing &&
      workspaces.some((item) => item.id === tutorial.workspaceId)
    )
      setSelected(tutorial.workspaceId);
  }, [
    tutorial?.active,
    tutorial?.workspaceId,
    enabled,
    changing,
    workspaces.length,
  ]);
  const jobs = assistant.jobs;
  const needsAttention = [...jobs]
    .sort((a, b) => b.created_at - a.created_at)
    .filter((job) => {
      const utterance = session?.utterances.find(
        (entry) => entry.utterance_id === job.utterance_id,
      );
      return (
        utterance?.text === job.text &&
        !["partial", "retracted"].includes(utterance.status) &&
        !["SUPERSEDED", "CANCELLED"].includes(job.state) &&
        (job.state === "FAILED" ||
          job.state === "AWAITING_CONTEXT" ||
          ["needs_clarification", "unsupported_action"].includes(
            job.result?.status ?? "",
          ))
      );
    });
  const processing = jobs.some((job) =>
    ["RUNNING", "CLASSIFYING", "QUEUED", "RETRY_WAIT"].includes(job.state),
  );
  const status = assistant.restoring
    ? "이전 안내를 불러오고 있습니다"
    : !enabled
      ? "문서 참고가 꺼져 있습니다"
      : !session
        ? "녹음하거나 파일을 올리면 관련 문서를 찾아드립니다"
        : processing
          ? "대화와 관련된 문서를 확인하고 있습니다"
          : "필요한 정보를 찾으면 이곳에 안내합니다";
  async function toggle() {
    if (changing) return;
    if (!enabled && (!canStart || !workspace || !diagnostics)) return;
    const controller = new AbortController();
    activation.current = controller;
    setActivating(true);
    try {
      if (
        !enabled &&
        workspace &&
        diagnostics &&
        workspace.consent !== diagnostics.llm.provider_id
      ) {
        const updated = await ragApi<Workspace>(
          `/workspaces/${workspace.id}`,
          {
            external_llm_approved: true,
            provider_id: diagnostics.llm.provider_id,
          },
          "PATCH",
          controller.signal,
        );
        if (controller.signal.aborted) return;
        setWorkspaces((previous) =>
          previous.map((item) => (item.id === updated.id ? updated : item)),
        );
      }
      if (!controller.signal.aborted) await assistant.setEnabled(!enabled);
    } catch (caught) {
      if (!controller.signal.aborted)
        setLoadError(
          reasonMessage(
            String(caught instanceof Error ? caught.message : caught),
          ),
        );
    } finally {
      setActivating(false);
    }
  }
  return (
    <aside className="meeting-assistant" aria-label="참고 문서 안내">
      <section className="panel meeting-controls">
        <div className="meeting-heading">
          <span className="meeting-symbol">
            <Sparkles size={21} />
          </span>
          <div>
            <h2>참고 문서</h2>
            <p>대화에 필요한 정보를 문서에서 찾아드립니다.</p>
          </div>
        </div>
        <label className="meeting-workspace-label" htmlFor="meeting-workspace">
          참고할 워크스페이스
        </label>
        <div className="meeting-workspace-row">
          <select
            id="meeting-workspace"
            value={selected}
            disabled={loading || changing || enabled || !workspaces.length}
            onChange={(event) => setSelected(event.target.value)}
          >
            {!workspaces.length && (
              <option value="">
                {loading ? "연결 확인 중…" : "워크스페이스 없음"}
              </option>
            )}
            {workspaces.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
                {w.active_revision_id ? "" : " · 문서 준비 필요"}
              </option>
            ))}
          </select>
          <button
            aria-label="자료 연결 상태 새로고침"
            title="연결 상태 새로고침"
            onClick={() => setReload((value) => value + 1)}
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? "meeting-spin" : ""} />
          </button>
        </div>
        <div className="meeting-readiness" role="status" aria-live="polite">
          {loading
            ? "문서를 불러오고 있습니다."
            : loadError
              ? `연결 확인 실패: ${loadError}`
              : blocked ||
                `${workspace?.document_count ?? 0}개 문서에서 관련 정보를 확인합니다.`}
        </div>
        <button className="meeting-manage" onClick={() => navigate("/rag")}>
          참고 문서 관리 <ArrowUpRight size={13} />
        </button>
        <button
          className={`meeting-toggle ${enabled ? "is-on" : "primary"}`}
          aria-pressed={enabled}
          disabled={changing || (!enabled && !canStart)}
          onClick={() => void toggle()}
        >
          <Sparkles size={16} />
          {changing
            ? "연결 중…"
            : enabled
              ? "문서 참고 끄기"
              : "문서 참고 켜기"}
        </button>
      </section>
      <div className="meeting-live-status" role="status" aria-live="polite">
        {processing && enabled ? (
          <LoaderCircle size={15} className="meeting-spin" />
        ) : (
          <span className={`meeting-status-dot ${enabled ? "is-on" : ""}`} />
        )}
        <span>{status}</span>
      </div>
      {assistant.error && (
        <div className="meeting-error" role="alert">
          <p>{assistant.error}</p>
          <span>
            연결을 다시 확인하고 있습니다. 작성된 대본과 안내는 그대로 남아
            있습니다.
          </span>
        </div>
      )}
      <div
        className="meeting-popups"
        aria-label="문서 기반 안내"
        aria-live="polite"
        aria-relevant="additions"
      >
        {session &&
          assistant.cards.map((card) => (
            <PopupCard
              key={card.result.popup!.id}
              card={card}
              session={session}
              dismiss={assistant.dismiss}
            />
          ))}
      </div>
      {!!needsAttention.length && (
        <details className="meeting-job-log" open>
          <summary>확인이 필요한 내용</summary>
          <div className="meeting-jobs">
            {needsAttention.map((job) => (
              <article key={job.id} className="meeting-job">
                <div className="meeting-job-heading">
                  <strong>
                    {job.state === "FAILED"
                      ? "문서를 확인하지 못했습니다"
                      : job.result?.status === "unsupported_action"
                        ? "도움이 필요한 요청"
                        : "조금 더 자세히 알려주세요"}
                  </strong>
                </div>
                <p className="meeting-job-quote">{job.text}</p>
                <p className="meeting-job-help">
                  {job.state === "FAILED"
                    ? reasonMessage(job.reason ?? undefined)
                    : job.result?.message ||
                      "어떤 내용을 확인하고 싶은지 이어서 말씀하거나 대본을 수정해 주세요."}
                </p>
                {job.state === "FAILED" && (
                  <>
                    <button
                      disabled={assistant.retryingId === job.id || !enabled}
                      onClick={() => void assistant.retry(job)}
                    >
                      <RefreshCw size={13} />
                      {assistant.retryingId === job.id
                        ? "확인 중…"
                        : "다시 확인하기"}
                    </button>
                    {!enabled && (
                      <small>문서 참고를 켠 후 다시 확인할 수 있습니다.</small>
                    )}
                  </>
                )}
              </article>
            ))}
          </div>
        </details>
      )}
      {assistant.snapshot?.next_cursor && (
        <button
          className="meeting-load-more"
          onClick={assistant.loadMore}
          disabled={assistant.loadingMore}
        >
          {assistant.loadingMore
            ? "이전 안내를 불러오는 중…"
            : "이전 안내 더 보기"}
        </button>
      )}
      {!assistant.cards.length && (
        <div className="meeting-empty">
          <Sparkles size={26} />
          <h3>
            {enabled
              ? "관련 정보를 여기에 모아드릴게요"
              : "대화 중에도 문서를 곁에"}
          </h3>
          <p>
            {enabled
              ? "대화에 도움이 되는 내용을 찾으면 출처와 함께 확인할 수 있습니다."
              : "워크스페이스를 선택하고 문서 참고를 켜보세요. 녹음과 파일 모두 함께 사용할 수 있습니다."}
          </p>
        </div>
      )}
    </aside>
  );
}
