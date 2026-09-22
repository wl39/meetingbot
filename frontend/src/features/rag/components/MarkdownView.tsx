import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import "./markdown.css";

/** Only small generated answers use client Markdown. Uploaded documents use
 * ServerDocument and never pass their original Markdown into this component. */
export default function MarkdownView({
  text,
  compact = false,
}: {
  text: string;
  compact?: boolean;
}) {
  return (
    <div className={`rag-markdown${compact ? " is-compact" : ""}`}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          table: ({ children }) => (
            <div className="rag-markdown-table">
              <table>{children}</table>
            </div>
          ),
          a: ({ href, children }) =>
            href && /^https?:\/\//i.test(href) ? (
              <a
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                referrerPolicy="no-referrer"
              >
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          img: ({ alt }) => (
            <span className="rag-markdown-image">
              [이미지: {alt || "첨부 이미지"}]
            </span>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
