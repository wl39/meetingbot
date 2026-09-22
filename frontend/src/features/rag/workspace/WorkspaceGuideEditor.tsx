import { useEffect, useRef, useState } from "react";
import { BookOpen, Check, Loader2, Save } from "lucide-react";
import { api, RagApiError, type WorkspaceGuide } from "../api";
import { message, time } from "../utils";

export default function WorkspaceGuideEditor({
  workspaceId,
}: {
  workspaceId: string;
}) {
  const [saved, setSaved] = useState<WorkspaceGuide | null>(null);
  const [content, setContent] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState<WorkspaceGuide | null>(null);
  const [reload, setReload] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const normalized = content.replace(/\r\n?/g, "\n").trim();
  const effectiveEnabled = enabled && !!normalized;
  const dirty =
    !!saved &&
    (normalized !== saved.content || effectiveEnabled !== saved.enabled);

  function accept(value: WorkspaceGuide) {
    setSaved(value);
    setContent(value.content);
    setEnabled(value.version === 0 || value.enabled);
    setConflict(null);
  }

  useEffect(() => {
    const c = new AbortController();
    controller.current = c;
    setSaved(null);
    setError("");
    setNotice("");
    api<WorkspaceGuide>(
      `/workspaces/${workspaceId}/guide`,
      undefined,
      undefined,
      c.signal,
    )
      .then((value) => {
        if (!c.signal.aborted && value.workspace_id === workspaceId)
          accept(value);
      })
      .catch((e) => {
        if (!c.signal.aborted) setError(message(e));
      });
    return () => c.abort();
  }, [workspaceId, reload]);

  async function save() {
    const signal = controller.current?.signal;
    if (!saved || pending || conflict || !dirty || signal?.aborted) return;
    setPending(true);
    setError("");
    setNotice("");
    try {
      const value = await api<WorkspaceGuide>(
        `/workspaces/${workspaceId}/guide`,
        {
          expected_version: saved.version,
          content: normalized,
          enabled: effectiveEnabled,
        },
        "PUT",
        signal,
      );
      if (signal?.aborted) return;
      if (value.workspace_id !== workspaceId)
        throw new Error("지침서의 워크스페이스를 확인할 수 없습니다.");
      accept(value);
      setNotice(
        value.enabled
          ? "지침서를 저장했습니다. 이후 시작하는 질문과 회의 검토에 참고합니다."
          : "지침서를 저장했습니다. 현재 답변에는 참고하지 않습니다.",
      );
    } catch (e) {
      if (signal?.aborted) return;
      setError(message(e));
      if (e instanceof RagApiError && e.code === "GUIDE_CHANGED") {
        try {
          const latest = await api<WorkspaceGuide>(
            `/workspaces/${workspaceId}/guide`,
            undefined,
            undefined,
            signal,
          );
          if (!signal?.aborted && latest.workspace_id === workspaceId)
            setConflict(latest);
        } catch {
          /* Keep the draft and stale version; never overwrite on failed refresh. */
        }
      }
    } finally {
      if (!signal?.aborted) setPending(false);
    }
  }

  return (
    <section
      className="rag-panel rag-setting rag-guide"
      aria-labelledby="workspace-guide-title"
    >
      <div className="rag-guide-heading">
        <h2 id="workspace-guide-title">
          <BookOpen size={20} />
          지침서
        </h2>
        {saved && (
          <span className="rag-guide-badge">
            {saved.enabled ? "참고 중" : "사용 안 함"}
          </span>
        )}
      </div>
      <p id="workspace-guide-help">
        이 워크스페이스에서 답변에 포함할 항목과 표현 방식을 정합니다. 운영
        기준과 문서 근거를 우선하며, 질문 답변과 회의 검토의 구성에 참고합니다.
      </p>
      {!saved ? (
        error ? (
          <div className="rag-guide-load-error" role="alert">
            <p>{error}</p>
            <button
              className="rag-secondary"
              onClick={() => setReload((v) => v + 1)}
            >
              다시 불러오기
            </button>
          </div>
        ) : (
          <p className="rag-guide-loading" role="status">
            <Loader2 size={16} className="rag-spin" /> 지침서를 불러오는 중…
          </p>
        )
      ) : (
        <>
          <label className="rag-guide-label" htmlFor="workspace-guide-content">
            지침서 내용
          </label>
          <textarea
            id="workspace-guide-content"
            aria-describedby="workspace-guide-help workspace-guide-count"
            rows={7}
            maxLength={saved.max_chars}
            value={content}
            disabled={pending}
            placeholder={
              "예: 요리 관련 답변에는 재료와 조리 순서를 포함해 주세요.\n조리 순서는 번호로 정리하고, 문서에서 확인되는 주의사항을 함께 안내해 주세요."
            }
            onChange={(e) => {
              setContent(e.target.value);
              setNotice("");
            }}
          />
          <div className="rag-guide-meta">
            <span>
              {dirty
                ? "저장하지 않은 변경사항"
                : saved.updated_at
                  ? `최근 저장 ${time(saved.updated_at)}`
                  : "아직 작성된 지침서가 없습니다."}
            </span>
            <span id="workspace-guide-count">
              {content.length.toLocaleString()} /{" "}
              {saved.max_chars.toLocaleString()}자
            </span>
          </div>
          <label className="rag-consent">
            <input
              type="checkbox"
              checked={enabled}
              disabled={pending}
              onChange={(e) => {
                setEnabled(e.target.checked);
                setNotice("");
              }}
            />
            질문과 회의 검토에 지침서 참고
          </label>
          <p className="rag-guide-hint">
            문서에 없는 사실이나 절차는 추가하지 않습니다. 비워서 저장하면
            지침서 사용이 해제됩니다.
          </p>
          {error && (
            <p className="rag-guide-error" role="alert">
              {error}
            </p>
          )}
          {conflict && (
            <div className="rag-guide-conflict">
              <h3>다른 화면에서 저장한 최신 지침서</h3>
              <p>
                {conflict.enabled ? "참고 중" : "사용 안 함"} ·{" "}
                {conflict.updated_at ? time(conflict.updated_at) : ""}
              </p>
              <pre>{conflict.content || "(내용 없음)"}</pre>
              <p>
                위 내용을 확인해 주세요. 작성 중인 수정본은 아직 저장되지
                않았습니다.
              </p>
              <div className="rag-guide-actions">
                <button
                  className="rag-secondary"
                  onClick={() => {
                    accept(conflict);
                    setError("");
                  }}
                >
                  최신 내용 사용
                </button>
                <button
                  className="rag-secondary"
                  onClick={() => {
                    setSaved(conflict);
                    setConflict(null);
                    setError("");
                  }}
                >
                  내 수정본으로 계속
                </button>
              </div>
            </div>
          )}
          <div className="rag-guide-actions">
            <button
              className="rag-primary"
              disabled={!dirty || pending || !!conflict}
              onClick={save}
            >
              {pending ? (
                <Loader2 size={16} className="rag-spin" />
              ) : (
                <Save size={16} />
              )}
              {pending ? "저장 중…" : "지침서 저장"}
            </button>
            <button
              className="rag-secondary"
              disabled={!dirty || pending}
              onClick={() => {
                accept(saved);
                setError("");
                setNotice("");
              }}
            >
              수정 취소
            </button>
          </div>
          {notice && (
            <p className="rag-guide-notice" role="status">
              <Check size={16} />
              {notice}
            </p>
          )}
        </>
      )}
    </section>
  );
}
