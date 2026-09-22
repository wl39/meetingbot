import { useCallback, useEffect, useRef, useState } from "react";
import { api as ragApi, type Workspace as RagWorkspace } from "../../rag/api";
import { errorMessage, type RagSettings } from "../api";

export type RagDraft = {
  version: number;
  chunk_tokens: number;
  overlap_tokens: number;
  top_k: number;
};
export type Embedding = { state: string; model?: string; error_code?: string };
export function useRetrievalSettings(active: boolean) {
  const [config, setConfig] = useState<RagSettings | null>(null);
  const [draft, setDraft] = useState<RagDraft | null>(null);
  const base = useRef<RagDraft | null>(null);
  const dirtyRef = useRef(false);
  const [indexJobs, setIndexJobs] = useState<RagWorkspace[]>([]);
  const [embedding, setEmbedding] = useState<Embedding | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = JSON.stringify(base.current) !== JSON.stringify(draft);
  dirtyRef.current = dirty;
  const load = useCallback(
    async (replace = false, isCurrent: () => boolean = () => true) => {
      const c = await ragApi<RagSettings>("/settings");
      if (!isCurrent()) return;
      setConfig(c);
      if (!base.current || replace || !dirtyRef.current) {
        const value = {
          version: c.version,
          chunk_tokens: c.chunk_tokens,
          overlap_tokens: c.overlap_tokens,
          top_k: c.top_k,
        };
        base.current = value;
        setDraft(value);
      }
    },
    [],
  );
  useEffect(() => {
    if (!active) return;
    let alive = true;
    let fetching = false;
    const tick = async () => {
      if (fetching) return;
      fetching = true;
      try {
        await load(false, () => alive);
        if (!alive) return;
        const result = await ragApi<Embedding>("/embedding");
        if (alive) setEmbedding(result);
        const workspaces = await ragApi<RagWorkspace[]>("/workspaces");
        if (alive) setIndexJobs(workspaces);
      } catch (e) {
        if (alive) setError(errorMessage(e));
      } finally {
        fetching = false;
      }
    };
    void tick();
    const timer = setInterval(tick, 4000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [active, load]);
  async function run(label: string, action: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  }
  const valid =
    !!draft &&
    !!config &&
    Number.isInteger(draft.chunk_tokens) &&
    Number.isInteger(draft.overlap_tokens) &&
    Number.isInteger(draft.top_k) &&
    draft.chunk_tokens >= config.limits.chunk_tokens.min &&
    draft.chunk_tokens <= config.limits.chunk_tokens.max &&
    draft.overlap_tokens >= 0 &&
    draft.overlap_tokens < draft.chunk_tokens &&
    draft.top_k >= config.limits.top_k.min &&
    draft.top_k <= config.limits.top_k.max;
  const embeddingBusy =
    !!embedding && ["LOADING", "DOWNLOADING"].includes(embedding.state);
  async function prepareEmbedding() {
    await run("검색 모델 준비 중", async () => {
      setEmbedding(await ragApi<Embedding>("/embedding/install", {}));
      setNotice(
        "검색 모델 준비를 시작했습니다. 완료되면 아래에서 자료를 재색인할 수 있습니다.",
      );
    });
  }
  async function save() {
    if (!draft || !valid || !dirty) return;
    await run("설정 저장 중", async () => {
      const result = await ragApi<RagSettings>(
        "/settings",
        {
          expected_version: draft.version,
          chunk_tokens: draft.chunk_tokens,
          overlap_tokens: draft.overlap_tokens,
          top_k: draft.top_k,
        },
        "PUT",
      );
      const next = {
        version: result.version,
        chunk_tokens: result.chunk_tokens,
        overlap_tokens: result.overlap_tokens,
        top_k: result.top_k,
      };
      setConfig(result);
      base.current = next;
      setDraft(next);
      setNotice(
        result.reindex_required
          ? "설정을 저장했습니다. 아래 자료를 재색인하면 새로운 청크 크기가 반영됩니다."
          : "설정을 저장했습니다. 다음 검색부터 적용됩니다.",
      );
    });
  }
  async function reindex(workspace: RagSettings["workspaces"][number]) {
    await run(workspace.workspace_id, async () => {
      await ragApi(`/workspaces/${workspace.workspace_id}/index-jobs`, {});
      await load();
      setNotice(
        `${workspace.name} 재색인을 시작했습니다. 자료 검색 화면에서 상세 진행 상황을 확인할 수 있습니다.`,
      );
    });
  }
  return {
    config,
    draft,
    indexJobs,
    embedding,
    busy,
    error,
    notice,
    dirty,
    valid,
    embeddingBusy,
    setDraft,
    prepareEmbedding,
    save,
    reindex,
    clearError: () => setError(""),
    reset: () => run("설정 불러오는 중", () => load(true)),
  };
}
