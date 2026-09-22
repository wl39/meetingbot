import { useEffect, useState } from "react";
import { api, type Job, type Workspace } from "../api";
import { busy, message } from "../utils";

export function useServerWorkspace({
  onCreated,
  onError,
}: {
  onCreated: (workspace: Workspace) => void;
  onError: (message: string) => void;
}) {
  const [roots, setRoots] = useState<{ id: string; label: string }[]>([]),
    [root, setRoot] = useState(""),
    [path, setPath] = useState(""),
    [entries, setEntries] = useState<
      { name: string; kind: string; reason: string | null }[]
    >([]),
    [cursor, setCursor] = useState<number | null>(null),
    [filter, setFilter] = useState(""),
    [name, setName] = useState(""),
    [preview, setPreview] = useState<Job | null>(null),
    [chosen, setChosen] = useState<{
      root_id: string;
      relative_path: string;
    } | null>(null),
    [loading, setLoading] = useState(false);
  useEffect(() => {
    let alive = true;
    api<{ roots: typeof roots }>("/source-roots")
      .then((r) => {
        if (alive) {
          setRoots(r.roots);
          setRoot(r.roots[0]?.id || "");
        }
      })
      .catch((e) => onError(message(e)));
    return () => {
      alive = false;
    };
  }, []);
  useEffect(() => {
    if (!root) return;
    const c = new AbortController();
    setEntries([]);
    setCursor(null);
    api<{ entries: typeof entries; next_cursor: number | null }>(
      `/source-roots/${encodeURIComponent(root)}/entries?relative_path=${encodeURIComponent(path)}&filter=${encodeURIComponent(filter)}`,
      undefined,
      undefined,
      c.signal,
    )
      .then((r) => {
        setEntries(r.entries);
        setCursor(r.next_cursor);
      })
      .catch((e) => {
        if (!c.signal.aborted) onError(message(e));
      });
    return () => c.abort();
  }, [root, path, filter]);
  useEffect(() => {
    if (!preview || !busy(preview)) return;
    let alive = true;
    const timer = setInterval(
      () =>
        api<Job>(`/source-previews/${preview.job_id}`)
          .then((j) => {
            if (alive) setPreview(j);
          })
          .catch((e) => {
            if (alive) onError(message(e));
          }),
      1000,
    );
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [preview?.job_id, preview?.state]);
  async function choose() {
    setLoading(true);
    try {
      const source = { root_id: root, relative_path: path };
      setChosen(source);
      setPreview(await api<Job>("/source-previews", source));
    } catch (e) {
      onError(message(e));
    } finally {
      setLoading(false);
    }
  }
  async function create() {
    if (!chosen) return;
    setLoading(true);
    try {
      const w = await api<Workspace>("/workspaces", {
        name,
        description: "",
        ...chosen,
      });
      await api(`/workspaces/${w.id}/index-jobs`, {});
      onCreated(w);
    } catch (e) {
      onError(message(e));
    } finally {
      setLoading(false);
    }
  }
  async function loadMore() {
    try {
      const result = await api<{
        entries: typeof entries;
        next_cursor: number | null;
      }>(
        `/source-roots/${root}/entries?relative_path=${encodeURIComponent(path)}&cursor=${cursor}&filter=${encodeURIComponent(filter)}`,
      );
      setEntries([...entries, ...result.entries]);
      setCursor(result.next_cursor);
    } catch (error) {
      onError(message(error));
    }
  }
  return {
    roots,
    root,
    path,
    entries,
    cursor,
    filter,
    name,
    preview,
    chosen,
    loading,
    setRoot,
    setPath,
    setFilter,
    setName,
    choose,
    create,
    loadMore,
  };
}
