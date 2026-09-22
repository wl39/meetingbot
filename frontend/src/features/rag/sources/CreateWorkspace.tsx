import { useState } from "react";
import { FolderOpen, HardDrive } from "lucide-react";
import type { Workspace } from "../api";
import FolderUpload from "../FolderUpload";
import ServerWorkspace from "./ServerWorkspace";
import { useWorkspace } from "../../../workspace/context";
export default function CreateWorkspace(props: {
  onClose: () => void;
  onCreated: (w: Workspace) => void;
  onError: (s: string) => void;
}) {
  const [mode, setMode] = useState("upload");
  const { access } = useWorkspace();
  const managesData = access.role === "admin" || access.role === "superadmin";
  return (
    <>
      <div className="rag-create-modes" aria-label="자료 등록 방식">
        <button
          className={mode === "upload" ? "active" : ""}
          onClick={() => setMode("upload")}
        >
          <FolderOpen size={17} />내 기기 폴더 업로드
        </button>
        {managesData && (
          <button
            className={mode === "server" ? "active" : ""}
            onClick={() => setMode("server")}
          >
            <HardDrive size={17} />
            공유 폴더 연결
          </button>
        )}
      </div>
      {mode === "upload" || !managesData ? (
        <FolderUpload {...props} />
      ) : (
        <ServerWorkspace {...props} />
      )}
    </>
  );
}
