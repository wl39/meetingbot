import { useEffect, useMemo, useRef } from "react";
import DOMPurify from "dompurify";
import type { RenderedPage } from "../useDocumentPage";
import "./markdown.css";

/** Display only a bounded, server-rendered page. No Markdown parsing here. */
export default function ServerDocument({
  page,
  compact = false,
  anchor,
  onAnchor,
  onDocumentLink,
}: {
  page: RenderedPage;
  compact?: boolean;
  anchor?: string;
  onAnchor: (anchor: string) => void;
  onDocumentLink: (href: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const safe = useMemo(
    () =>
      DOMPurify.sanitize(page.html, {
        ALLOWED_TAGS: [
          "p",
          "div",
          "span",
          "h1",
          "h2",
          "h3",
          "h4",
          "h5",
          "h6",
          "ul",
          "ol",
          "li",
          "blockquote",
          "pre",
          "code",
          "strong",
          "em",
          "s",
          "a",
          "sup",
          "section",
          "table",
          "thead",
          "tbody",
          "tr",
          "th",
          "td",
          "br",
          "hr",
          "input",
        ],
        ALLOWED_ATTR: [
          "href",
          "title",
          "class",
          "start",
          "value",
          "type",
          "checked",
          "disabled",
        ],
        ALLOW_DATA_ATTR: true,
        FORBID_ATTR: ["id", "name", "style", "src", "srcset"],
      }),
    [page.html],
  );
  function scroll(target: string) {
    const node = Array.from(
      container.current?.querySelectorAll<HTMLElement>(
        "[data-document-anchor],[data-document-id]",
      ) || [],
    ).find(
      (node) =>
        node.dataset.documentAnchor === target ||
        node.dataset.documentId === target,
    );
    if (!node) return false;
    node.scrollIntoView({ block: "start" });
    node.tabIndex = -1;
    node.focus({ preventScroll: true });
    return true;
  }
  useEffect(() => {
    if (anchor) scroll(anchor);
  }, [safe, anchor]);
  return (
    <div>
      {!page.anchor_found && (
        <p className="rag-markdown-context" role="status">
          연결된 제목을 찾을 수 없습니다. 문서 목차에서 확인해 주세요.
        </p>
      )}
      <div
        ref={container}
        className={`rag-markdown rag-server-document${compact ? " is-compact" : ""}`}
        onClick={(event) => {
          const link = (event.target as Element).closest<HTMLAnchorElement>(
            "a[href]",
          );
          if (!link) return;
          event.preventDefault();
          const href = link.getAttribute("href") || "";
          if (href.startsWith("#")) {
            let target = href.slice(1);
            try {
              target = decodeURIComponent(target).normalize("NFC");
            } catch {
              /* literal */
            }
            if (!scroll(target)) onAnchor(target);
          } else if (/^https?:\/\//i.test(href)) {
            window.open(href, "_blank", "noopener,noreferrer");
          } else if (!/^(?:[a-z][\w+.-]*:|\/|\\)/i.test(href))
            onDocumentLink(href);
        }}
        dangerouslySetInnerHTML={{ __html: safe }}
      />
    </div>
  );
}
