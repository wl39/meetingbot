import { useState } from "react";
import type { Evidence } from "../api";
import { useDocumentPage } from "../useDocumentPage";
import EvidencePanel from "../workspace/EvidencePanel";
import ServerDocument from "./ServerDocument";

/** A retrieval fragment is never interpreted as a standalone Markdown document. */
export default function EvidencePreview({ evidence }: { evidence: Evidence }) {
  const { document, error, retry } = useDocumentPage(evidence, {
    mode: "preview",
  });
  const [link, setLink] = useState<string | null>(null);
  return (
    <>
      {error ? (
        <div className="rag-markdown-context" role="status">
          {error} <button onClick={retry}>다시 시도</button>
        </div>
      ) : !document ? (
        <p className="rag-markdown-context" role="status">
          문서 구조를 불러오는 중…
        </p>
      ) : document.kind !== "rendered_page" ? (
        <p className="rag-markdown-context">
          원문에서 문서 내용을 확인해 주세요.
        </p>
      ) : (
        <div className="rag-markdown-excerpt">
          <p className="rag-markdown-context">
            문서 구조에 맞춰 관련 내용을 표시합니다.
            <span>
              표시 범위 · {document.start_line}–{document.end_line}줄
            </span>
          </p>
          <ServerDocument
            page={document}
            compact
            onDocumentLink={setLink}
            onAnchor={(value) => setLink(`#${value}`)}
          />
          {document.continued && (
            <p className="rag-markdown-context">
              긴 표·목록은 구간을 나누어 표시합니다. 원문에서 이어서 확인하세요.
            </p>
          )}
          <button className="rag-context-toggle" onClick={() => setLink("")}>
            원문에서 이어 보기
          </button>
        </div>
      )}
      {link !== null && (
        <EvidencePanel
          evidence={evidence}
          initialLink={link}
          onClose={() => setLink(null)}
        />
      )}
    </>
  );
}
