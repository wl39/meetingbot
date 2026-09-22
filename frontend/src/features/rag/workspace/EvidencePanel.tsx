import "../rag.css";
import { FeedbackMessage } from "../../../components/ui/FeedbackMessage";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft, Layers, List, Loader2, X } from "lucide-react";
import { api, locationLabel, type Evidence } from "../api";
import { message } from "../utils";
import FilePath from "../components/FilePath";
import ServerDocument from "../components/ServerDocument";
import { documentLink } from "../document-links";
import SpreadsheetView from "../components/SpreadsheetView";
import { useDocumentPage, type PageOptions } from "../useDocumentPage";

function anchorOf(link: string) {
  const value = link.includes("#") ? link.slice(link.indexOf("#") + 1) : "";
  try {
    return decodeURIComponent(value).normalize("NFC");
  } catch {
    return value;
  }
}
export default function EvidencePanel({
  evidence,
  initialLink = "",
  onClose,
}: {
  evidence: Evidence;
  initialLink?: string;
  onClose: () => void;
}) {
  const [e, setEvidence] = useState(evidence);
  const [previous, setPrevious] = useState<
    { evidence: Evidence; anchor: string }[]
  >([]);
  const [anchor, setAnchor] = useState(
    initialLink.startsWith("#") ? anchorOf(initialLink) : "",
  );
  const [options, setOptions] = useState<PageOptions>({
    mode: "document",
    anchor: initialLink.startsWith("#") ? anchorOf(initialLink) : undefined,
  });
  const [sourceHistory, setSourceHistory] = useState<number[]>([]);
  const [opening, setOpening] = useState(
    Boolean(initialLink && !initialLink.startsWith("#")),
  );
  const {
    document: doc,
    error: snapshotError,
    retry,
  } = useDocumentPage(e, options, !opening);
  const [error, setError] = useState("");
  const navigation = useRef<AbortController | null>(null);
  useEffect(() => () => navigation.current?.abort(), []);
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);
  useEffect(() => {
    if (initialLink && !initialLink.startsWith("#"))
      void openLinkedDocument(initialLink);
  }, [initialLink]);
  async function openLinkedDocument(href: string) {
    const path = documentLink(e.relative_path, href);
    if (!path) {
      setError("이 링크는 문서 뷰어에서 열 수 없습니다.");
      setOpening(false);
      return;
    }
    navigation.current?.abort();
    const controller = new AbortController();
    navigation.current = controller;
    setOpening(true);
    setError("");
    try {
      const result = await api<{ evidence: Evidence }>(
        `/workspaces/${e.workspace_id}/documents?metadata_only=true&revision_id=${encodeURIComponent(e.revision_id)}&relative_path=${encodeURIComponent(path)}`,
        undefined,
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        if (
          result.evidence.workspace_id !== e.workspace_id ||
          result.evidence.revision_id !== e.revision_id
        )
          throw new Error("연결된 문서를 확인하지 못했습니다.");
        setPrevious((items) => [...items, { evidence: e, anchor }]);
        setAnchor(anchorOf(href));
        setOptions({ mode: "document", anchor: anchorOf(href) || undefined });
        setEvidence(result.evidence);
      }
    } catch (error) {
      if (!controller.signal.aborted) setError(message(error));
    } finally {
      if (!controller.signal.aborted) setOpening(false);
    }
  }
  const textDocument = /\.(?:md|txt)$/i.test(e.relative_path);
  useEffect(() => {
    setError("");
    setSourceHistory([]);
  }, [e.workspace_id, e.revision_id, e.evidence_id]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [onClose]);
  return createPortal(
    <div className="rag-shell rag-drawer-backdrop" onClick={onClose}>
      <section
        className="rag-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="문서 원문"
        onClick={(event) => event.stopPropagation()}
      >
        <header>
          <div>
            <h2>
              <FilePath path={e.relative_path} />
            </h2>
            <p>
              {e.source_preview
                ? "원본 파일 미리보기"
                : `인용 위치 · ${locationLabel(e)}`}
            </p>
          </div>
          <button aria-label="원문 닫기" onClick={onClose} autoFocus>
            <X size={23} />
          </button>
        </header>
        {!!previous.length && (
          <button
            className="rag-document-back"
            disabled={opening}
            onClick={() => {
              const last = previous[previous.length - 1];
              setEvidence(last.evidence);
              setAnchor(last.anchor);
              setOptions({
                mode: "document",
                anchor: last.anchor || undefined,
              });
              setPrevious((items) => items.slice(0, -1));
            }}
          >
            <ArrowLeft size={15} />
            이전 문서
          </button>
        )}
        <div className="rag-snapshot-note">
          <Layers size={16} />
          {e.source_preview
            ? "아직 검색에 포함되지 않은 현재 원본 파일입니다."
            : textDocument
              ? "등록된 문서의 원문입니다. 목차와 링크로 필요한 내용을 확인하세요."
              : "등록된 표의 원문입니다. 시트를 선택하고 행을 이동해 전체 내용을 확인하세요."}
        </div>
        {textDocument && !e.source_preview && (
          <div className="rag-tabs rag-viewer-tabs" aria-label="문서 보기 방식">
            <button
              className={options.mode !== "source" ? "active" : ""}
              aria-pressed={options.mode !== "source"}
              onClick={() =>
                setOptions({ mode: "document", anchor: anchor || undefined })
              }
            >
              문서 보기
            </button>
            <button
              className={options.mode === "source" ? "active" : ""}
              aria-pressed={options.mode === "source"}
              onClick={() => {
                setSourceHistory([]);
                setOptions({ mode: "source" });
              }}
            >
              원문 · 줄 번호
            </button>
          </div>
        )}
        {opening ? (
          <div className="rag-small-empty">
            <Loader2 className="rag-spin" />
            문서를 여는 중
          </div>
        ) : error || snapshotError ? (
          <FeedbackMessage tone="error" className="rag-inline-error">
            {error || snapshotError}
            {snapshotError && <button onClick={retry}>다시 시도</button>}
          </FeedbackMessage>
        ) : !doc ? (
          <div className="rag-small-empty">
            <Loader2 className="rag-spin" />
            원문 확인 중
          </div>
        ) : doc.kind === "rendered_page" ? (
          <>
            <div className="rag-document-pagination">
              <button
                disabled={doc.previous_page === null}
                onClick={() => {
                  setAnchor("");
                  setOptions({ mode: "document", page: doc.previous_page! });
                }}
              >
                이전 구간
              </button>
              <span>
                {doc.start_line}–{doc.end_line}줄 표시
              </span>
              <button
                disabled={doc.next_page === null}
                onClick={() => {
                  setAnchor("");
                  setOptions({ mode: "document", page: doc.next_page! });
                }}
              >
                다음 구간
              </button>
            </div>
            <div className="rag-document-layout">
              <div className="rag-document-body">
                {doc.continued && (
                  <p className="rag-markdown-context">
                    긴 표·목록의 일부 구간입니다. 앞뒤 구간에서 이어서 확인할 수
                    있습니다.
                  </p>
                )}
                <ServerDocument
                  page={doc}
                  anchor={anchor}
                  onAnchor={(value) => {
                    setAnchor(value);
                    setOptions({ mode: "document", anchor: value });
                  }}
                  onDocumentLink={(href) => void openLinkedDocument(href)}
                />
              </div>
              {!!doc.outline_total && (
                <nav className="rag-document-outline" aria-label="문서 목차">
                  <strong>
                    <List size={16} />
                    목차
                  </strong>
                  {doc.headings.map((heading) => (
                    <button
                      key={heading.anchor}
                      className={`level-${heading.level}`}
                      onClick={() => {
                        setAnchor(heading.anchor);
                        setOptions({
                          mode: "document",
                          anchor: heading.anchor,
                          outlineOffset: doc.outline_offset,
                        });
                      }}
                    >
                      {heading.title}
                    </button>
                  ))}
                  {doc.outline_offset > 0 && (
                    <button
                      onClick={() =>
                        setOptions({
                          ...options,
                          page: doc.page,
                          outlineOffset: Math.max(0, doc.outline_offset - 80),
                        })
                      }
                    >
                      이전 목차
                    </button>
                  )}
                  {doc.outline_offset + doc.headings.length <
                    doc.outline_total && (
                    <button
                      onClick={() =>
                        setOptions({
                          ...options,
                          page: doc.page,
                          outlineOffset:
                            doc.outline_offset + doc.headings.length,
                        })
                      }
                    >
                      다음 목차
                    </button>
                  )}
                </nav>
              )}
            </div>
          </>
        ) : doc.kind === "spreadsheet_page" ? (
          <SpreadsheetView
            document={doc}
            evidence={e}
            onPage={(page, sheet) =>
              setOptions({ mode: "document", page, sheet })
            }
          />
        ) : doc.kind === "source_page" ? (
          <>
            <div className="rag-document-pagination">
              <button
                disabled={!sourceHistory.length}
                onClick={() => {
                  const offset = sourceHistory[sourceHistory.length - 1];
                  setSourceHistory((items) => items.slice(0, -1));
                  setOptions({ mode: "source", sourceOffset: offset });
                }}
              >
                이전 원문
              </button>
              <span>
                원문 {doc.start_line}줄부터
                {doc.mid_line ? " (앞 구간에서 계속)" : ""}
              </span>
              <button
                disabled={doc.next_offset === null}
                onClick={() => {
                  setSourceHistory((items) => [...items, doc.offset]);
                  setOptions({
                    mode: "source",
                    sourceOffset: doc.next_offset!,
                  });
                }}
              >
                다음 원문
              </button>
            </div>
            <div className="rag-source-lines">
              {doc.text.split("\n").map((line, i) => (
                <div
                  className={
                    i + doc.start_line >= (e.location.start_line || 0) &&
                    i + doc.start_line <= (e.location.end_line || 0)
                      ? "highlight"
                      : ""
                  }
                  key={i}
                >
                  <span>{i + doc.start_line}</span>
                  <code>{line || " "}</code>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="rag-source-table">
            <h3>
              {e.location.sheet} · {e.location.cell_range}
            </h3>
            <table>
              <thead>
                <tr>
                  <th>셀</th>
                  <th>열 이름</th>
                  <th>원본 값</th>
                  <th>형식 / 수식 상태</th>
                </tr>
              </thead>
              <tbody>
                {e.table?.cells.map((cell, i) => (
                  <tr key={cell.address}>
                    <th>{cell.address}</th>
                    <td>{e.table?.headers[i]}</td>
                    <td>
                      {cell.value === null ? (
                        <em>빈 값</em>
                      ) : (
                        String(cell.value)
                      )}
                      {cell.formula && <code>{cell.formula}</code>}
                    </td>
                    <td>
                      {cell.number_format || cell.type}
                      {cell.formula_status && (
                        <small>
                          {cell.formula_status === "cache_missing"
                            ? "저장된 계산 결과 없음"
                            : "계산 결과 최신성 확인 필요"}
                        </small>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p>수식의 값은 파일을 저장한 시점 기준입니다.</p>
          </div>
        )}
      </section>
    </div>,
    document.body,
  );
}
