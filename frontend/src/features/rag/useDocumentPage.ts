import { useEffect, useState } from "react";
import { api, RagApiError, type Cell, type Evidence } from "./api";

export type Heading = {
  anchor: string;
  title: string;
  level: number;
  line: number;
  page: number;
};
export type RenderedPage = {
  kind: "rendered_page";
  html: string;
  start_line: number;
  end_line: number;
  page: number;
  last_page: number;
  total_pages: number;
  previous_page: number | null;
  next_page: number | null;
  headings: Heading[];
  outline_offset: number;
  outline_total: number;
  anchor_found: boolean;
  continued: boolean;
  html_bytes: number;
};
export type SourcePage = {
  kind: "source_page";
  text: string;
  start_line: number;
  mid_line: boolean;
  offset: number;
  next_offset: number | null;
  total_bytes: number;
  total_lines: number;
};
export type SpreadsheetPage = {
  kind: "spreadsheet_page";
  sheet: string;
  sheets: { name: string; rows: number }[];
  columns: string[];
  rows: { row: number; cells: Cell[] }[];
  page: number;
  total_pages: number;
  previous_page: number | null;
  next_page: number | null;
  merged_ranges: number[][];
  truncated: boolean;
};
export type DocumentPage =
  RenderedPage | SourcePage | SpreadsheetPage | { kind: "table_evidence" };
export type PageOptions = {
  mode: "preview" | "document" | "source";
  page?: number;
  anchor?: string;
  outlineOffset?: number;
  sourceOffset?: number;
  sheet?: string;
};

export function useDocumentPage(
  evidence: Evidence,
  options: PageOptions,
  enabled = true,
) {
  const {
    workspace_id: workspace,
    revision_id: revision,
    evidence_id: id,
  } = evidence;
  const params = new URLSearchParams({
    revision_id: revision,
    view: options.mode,
  });
  if (options.sheet) params.set("sheet", options.sheet);
  if (options.page !== undefined) params.set("page", String(options.page));
  if (options.anchor) params.set("anchor", options.anchor);
  if (options.outlineOffset)
    params.set("outline_offset", String(options.outlineOffset));
  if (options.sourceOffset !== undefined)
    params.set("source_offset", String(options.sourceOffset));
  if (evidence.source_preview)
    params.set("relative_path", evidence.relative_path);
  const query = params.toString();
  const key = JSON.stringify([workspace, id, query]);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    key: string;
    document: DocumentPage | null;
    error: string;
  }>({ key: "", document: null, error: "" });
  useEffect(() => {
    const controller = new AbortController();
    setState({ key, document: null, error: "" });
    if (!enabled) return () => controller.abort();
    api<{ workspace_id: string; revision_id: string; document: DocumentPage }>(
      evidence.source_preview
        ? `/workspaces/${encodeURIComponent(workspace)}/source-preview?${query}`
        : `/workspaces/${encodeURIComponent(workspace)}/evidence/${encodeURIComponent(id)}?${query}`,
      undefined,
      undefined,
      controller.signal,
    )
      .then((response) => {
        if (controller.signal.aborted) return;
        if (
          response.workspace_id !== workspace ||
          response.revision_id !== revision ||
          !response.document
        )
          throw new Error("Document scope mismatch");
        const doc = response.document;
        if (
          doc.kind === "rendered_page" &&
          (typeof doc.html !== "string" ||
            new TextEncoder().encode(doc.html).length > 48 * 1024 ||
            doc.headings.length > 80)
        )
          throw new Error("Document page exceeds limit");
        if (
          doc.kind === "source_page" &&
          (typeof doc.text !== "string" ||
            new TextEncoder().encode(doc.text).length > 16 * 1024)
        )
          throw new Error("Source page exceeds limit");
        if (
          ![
            "rendered_page",
            "source_page",
            "table_evidence",
            "spreadsheet_page",
          ].includes(doc.kind)
        )
          throw new Error("Unknown document type");
        setState({ key, document: doc, error: "" });
      })
      .catch((error) => {
        if (!controller.signal.aborted)
          setState({
            key,
            document: null,
            error: error instanceof RagApiError ? error.message : "문서 내용을 불러오지 못했습니다. 다시 시도해 주세요.",
          });
      });
    return () => controller.abort();
  }, [
    workspace,
    revision,
    id,
    query,
    key,
    attempt,
    enabled,
    evidence.source_preview,
  ]);
  return {
    ...(enabled && state.key === key ? state : { document: null, error: "" }),
    retry: () => setAttempt((value) => value + 1),
  };
}
