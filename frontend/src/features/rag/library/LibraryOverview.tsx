import { ArrowUpRight, FolderOpen, Plus } from "lucide-react";
import type { SearchResult, Workspace } from "../api";
import { Badge } from "../components/SourceFiles";
import { useWorkspace } from "../../../workspace/context";
import ResumeQuestion from "../history/ResumeQuestion";

export default function LibraryOverview({
  workspaces,
  onSelect,
  onCreate,
  onContinue,
}: {
  workspaces: Workspace[];
  onSelect: (id: string) => void;
  onCreate: () => void;
  onContinue: (result: SearchResult) => void;
}) {
  const { access, credential } = useWorkspace();
  const guest = access.keyless && !credential;
  return (
    <>
      <div className="rag-title-row">
        <div>
          <h1>자료 라이브러리</h1>
          <p>
            {guest
              ? "로그인 없이 파일이나 폴더를 올려 내 워크스페이스를 만들 수 있습니다."
              : "업무 문서를 한곳에 모으고, 질문과 회의 검토에 활용하세요."}
          </p>
        </div>
        <button className="rag-primary" onClick={onCreate}>
          <Plus size={17} />
          워크스페이스 만들기
        </button>
      </div>
      <ResumeQuestion onContinue={onContinue} />
      <div className="rag-section-heading">
        <h2>내 워크스페이스</h2>
        <span>공용 자료와 내가 올린 자료를 검색할 수 있습니다.</span>
      </div>
      <div className="rag-workspace-cards">
        {workspaces.map((w) => (
          <button
            className="rag-space-card"
            key={w.id}
            onClick={() => onSelect(w.id)}
          >
            <div>
              <span className="rag-folder-icon">
                <FolderOpen size={24} />
              </span>
              {(w.access_state && w.access_state !== "AVAILABLE") ||
              w.state !== "READY" ? (
                <Badge
                  state={
                    w.access_state && w.access_state !== "AVAILABLE"
                      ? "PARTIAL"
                      : w.state
                  }
                />
              ) : null}
            </div>
            <h3>{w.name}</h3>
            <small>
              {w.visibility === "private" ? "개인 자료" : "공용 자료"}
            </small>
            <p>
              {w.description ||
                w.source?.label ||
                "워크스페이스의 자료를 검색하고 질문하세요."}
            </p>
            <footer>
              <span>{w.document_count}개 문서</span>
              <ArrowUpRight size={17} />
            </footer>
          </button>
        ))}
        <button className="rag-add-card" onClick={onCreate}>
          <Plus size={27} />
          <strong>새 자료 연결</strong>
          <span>내 기기의 파일이나 폴더를 올려 검색하세요.</span>
        </button>
      </div>
    </>
  );
}
