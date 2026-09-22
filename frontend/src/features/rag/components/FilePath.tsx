import { Folder } from "lucide-react";

export default function FilePath({ path }: { path: string }) {
  const parts = path.split("/");
  const name = parts.pop() || path;
  return (
    <span className="rag-file-path" title={path}>
      <strong>{name}</strong>
      <small className="rag-file-folder">
        <Folder size={13} aria-hidden="true" />
        {parts.join("/") || "최상위 폴더"}
      </small>
    </span>
  );
}
