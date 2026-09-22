import { FeedbackMessage } from "../../components/ui/FeedbackMessage";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  FileText,
  FolderUp,
  Loader2,
  Upload,
  X,
} from "lucide-react";
import { api, uploadFile, type Job, type Workspace } from "./api";
import { formatBytes, selectFolder, type UploadLimits } from "./folder-upload";
import "./upload.css";
import FilePath from "./components/FilePath";
import FileBrowser from "./components/FileBrowser";
import { useWorkspace } from "../../workspace/context";

type FileStatus = "uploading" | "completed" | "failed";

type Session = {
  id: string;
  state: string;
  files: { id: string; path: string; size: number; received: boolean }[];
};
export default function FolderUpload({
  onClose,
  onCreated,
  onError,
}: {
  onClose: () => void;
  onCreated: (w: Workspace) => void;
  onError: (message: string) => void;
}) {
  const { access } = useWorkspace();
  const [limits, setLimits] = useState<UploadLimits | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [fileStatus, setFileStatus] = useState<Record<string, FileStatus>>({});
  const [created, setCreated] = useState<Workspace | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState("");
  const [sent, setSent] = useState(0);
  const [done, setDone] = useState(0);
  const [retry, setRetry] = useState(false);
  const session = useRef<Session | null>(null);
  const controller = useRef<AbortController | null>(null);
  const completed = useRef(false);
  const mounted = useRef(true);
  const picker = useRef<HTMLInputElement>(null);
  const filePicker = useRef<HTMLInputElement>(null);
  const selection = useMemo(
    () => (limits ? selectFolder(files, limits, selected) : null),
    [files, limits, selected],
  );
  useEffect(() => {
    mounted.current = true;
    api<UploadLimits>("/uploads/limits")
      .then((r) => {
        if (mounted.current) setLimits(r);
      })
      .catch((e) => {
        if (mounted.current) setError(e.message);
      });
    return () => {
      mounted.current = false;
      controller.current?.abort();
      if (session.current && !completed.current)
        void api(`/uploads/${session.current.id}`, undefined, "DELETE").catch(
          () => {},
        );
    };
  }, []);
  useEffect(() => {
    if (!busy) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);
  function choose(list: FileList | null) {
    const next = Array.from(list || []);
    if (!next.length || !limits) return;
    if (session.current && !completed.current)
      void api(`/uploads/${session.current.id}`, undefined, "DELETE").catch(
        () => {},
      );
    session.current = null;
    completed.current = false;
    setFiles(next);
    setSelected(
      new Set(selectFolder(next, limits).accepted.map((f) => f.path)),
    );
    setFileStatus({});
    setCreated(null);
    setName(selectFolder(next, limits).folder.slice(0, 100));
    setError("");
    setRetry(false);
    setSent(0);
    setDone(0);
    setPhase("");
  }
  async function transfer() {
    if (busy || created || !selection || selection.error || !name.trim())
      return;
    const ctrl = new AbortController();
    controller.current = ctrl;
    setBusy(true);
    setError("");
    setPhase("전송 준비 중");
    let activePath = "";
    try {
      if (!session.current) {
        session.current = await api<Session>("/uploads", {
          name: name.trim(),
          description,
          folder_name: selection.folder,
          files: selection.accepted.map((f) => ({
            path: f.path,
            size: f.file.size,
          })),
        });
      } else {
        session.current = await api<Session>(`/uploads/${session.current.id}`);
      }
      const current = session.current;
      if (ctrl.signal.aborted) {
        void api(`/uploads/${current.id}`, undefined, "DELETE").catch(() => {});
        return;
      }
      let acknowledged = current.files
        .filter((f) => f.received)
        .reduce((n, f) => n + f.size, 0);
      let count = current.files.filter((f) => f.received).length;
      setSent(acknowledged);
      setDone(count);
      setFileStatus(
        Object.fromEntries(
          current.files
            .filter((f) => f.received)
            .map((f) => [f.path, "completed"]),
        ),
      );
      const local = new Map(selection.accepted.map((f) => [f.path, f.file]));
      for (const file of current.files) {
        if (file.received) continue;
        const content = local.get(file.path);
        if (!content) throw new Error("원본 폴더를 다시 선택하세요.");
        activePath = file.path;
        setFileStatus((previous) => ({
          ...previous,
          [file.path]: "uploading",
        }));
        setPhase(file.path);
        await uploadFile(
          `/uploads/${current.id}/files/${file.id}`,
          content,
          ctrl.signal,
          (bytes) => {
            if (mounted.current) setSent(acknowledged + bytes);
          },
        );
        ctrl.signal.throwIfAborted();
        file.received = true;
        setFileStatus((previous) => ({
          ...previous,
          [file.path]: "completed",
        }));
        activePath = "";
        acknowledged += file.size;
        setDone(++count);
        setSent(acknowledged);
      }
      ctrl.signal.throwIfAborted();
      setPhase("전송 완료 · 자료 등록 중");
      // Commit is idempotent. A lost response can be retried without duplicate workspaces.
      const result = await api<{
        workspace: Workspace;
        job: Job | null;
        index_error: string | null;
      }>(`/uploads/${current.id}/commit`, {});
      completed.current = true;
      if (mounted.current) {
        setCreated(result.workspace);
        setRetry(false);
        setPhase(
          result.index_error
            ? "업로드 완료 · 워크스페이스에서 자료 준비를 다시 시도하세요."
            : "업로드 완료 · 검색 자료를 준비하고 있습니다.",
        );
        if (result.index_error)
          onError(
            "파일 업로드는 완료했지만 아직 검색할 수 없습니다. 워크스페이스에서 ‘자료 새로고침’을 눌러 다시 시도해 주세요.",
          );
      }
    } catch (e) {
      if (mounted.current && !ctrl.signal.aborted) {
        if (activePath)
          setFileStatus((previous) => ({
            ...previous,
            [activePath]: "failed",
          }));
        setError(
          e instanceof Error ? e.message : "업로드를 완료하지 못했습니다.",
        );
        setRetry(true);
      }
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function cancel() {
    controller.current?.abort();
    setBusy(true);
    try {
      if (session.current)
        await api(`/uploads/${session.current.id}`, undefined, "DELETE");
      session.current = null;
      setRetry(false);
      setSent(0);
      setDone(0);
      setPhase("");
      setError("");
      setFileStatus({});
    } catch (e) {
      setError(e instanceof Error ? e.message : "취소를 다시 시도하세요.");
    } finally {
      setBusy(false);
    }
  }
  const percent = selection?.bytes
    ? Math.min(100, Math.round((sent / selection.bytes) * 100))
    : selection?.accepted.length
      ? Math.round((done / selection.accepted.length) * 100)
      : 0;
  const committing = busy && phase === "전송 완료 · 자료 등록 중";
  const selectionLocked = busy || retry || !!created;
  return (
    <div className="rag-upload">
      <button className="rag-back" disabled={busy} onClick={onClose}>
        <ArrowLeft size={16} />
        라이브러리로 돌아가기
      </button>
      <div className="rag-title-row">
        <div>
          <h1>문서 등록</h1>
          <p>
            업무 문서를 등록하면 필요한 내용을 질문하고, 회의에서 나온 내용을
            확인할 수 있습니다.
          </p>
        </div>
      </div>
      {error && (
        <FeedbackMessage tone="error" className="rag-alert">
          {error}
        </FeedbackMessage>
      )}
      <div className="rag-upload-grid">
        <section className="rag-panel">
          <div className="rag-upload-picker">
            <span className="rag-folder-icon">
              <FolderUp size={30} />
            </span>
            <h2>
              {selection?.picked.length
                ? selection.folder
                : "등록할 문서를 선택하세요"}
            </h2>
            <p>MD · TXT · CSV · TSV · XLSX</p>
            <input
              ref={(node) => {
                picker.current = node;
                node?.setAttribute("webkitdirectory", "");
              }}
              type="file"
              multiple
              hidden
              aria-label="업로드할 폴더"
              disabled={selectionLocked}
              onChange={(e) => {
                choose(e.target.files);
                e.target.value = "";
              }}
            />
            <input
              ref={filePicker}
              type="file"
              multiple
              hidden
              aria-label="업로드할 파일"
              accept={limits?.extensions.join(",")}
              disabled={selectionLocked}
              onChange={(e) => {
                choose(e.target.files);
                e.target.value = "";
              }}
            />
            <div className="rag-upload-buttons">
              <button
                className="rag-primary"
                disabled={!limits || selectionLocked}
                onClick={() => picker.current?.click()}
              >
                <FolderUp size={17} />
                폴더 선택
              </button>
              <button
                className="rag-secondary"
                disabled={!limits || selectionLocked}
                onClick={() => filePicker.current?.click()}
              >
                <FileText size={17} />
                파일 선택
              </button>
            </div>
            <small>
              폴더 선택이 지원되지 않는 기기에서는 여러 파일을 선택할 수
              있습니다.
            </small>
            {limits && (
              <small>
                파일당 {formatBytes(limits.max_file_bytes)} · 합계{" "}
                {formatBytes(limits.max_total_bytes)} · 파일과 하위 폴더{" "}
                {limits.max_files.toLocaleString()}개
              </small>
            )}
          </div>
          {!!selection?.picked.length && (
            <>
              <div className="rag-panel-heading">
                <h2>등록할 문서</h2>
                <span>
                  {selection.accepted.length}개 · {formatBytes(selection.bytes)}
                </span>
              </div>
              <div className="rag-upload-selection">
                <span>{selection.accepted.length}개 선택</span>
                <button
                  className="rag-secondary"
                  disabled={selectionLocked}
                  onClick={() =>
                    setSelected(
                      new Set(
                        selection.picked
                          .filter((f) => !f.reason)
                          .map((f) => f.path),
                      ),
                    )
                  }
                >
                  전체 선택
                </button>
                <button
                  className="rag-secondary"
                  disabled={selectionLocked || !selected.size}
                  onClick={() => setSelected(new Set())}
                >
                  전체 해제
                </button>
              </div>
              {!!selection.picked.filter((f) => f.reason).length && (
                <p className="rag-upload-note">
                  {selection.picked.filter((f) => f.reason).length}개는 아래
                  이유로 전송에서 제외됩니다.
                </p>
              )}
              <FileBrowser
                key={files[0]?.webkitRelativePath || files[0]?.name}
                rootLabel={selection.folder}
                items={selection.picked.map((f) => ({
                  ...f,
                  attention: !!f.reason || fileStatus[f.path] === "failed",
                }))}
                selection={{
                  selected,
                  disabled: selectionLocked,
                  eligible: (f) => !f.reason,
                  toggle: (paths, checked) =>
                    setSelected((previous) => {
                      const next = new Set(previous);
                      paths.forEach((path) =>
                        checked ? next.add(path) : next.delete(path),
                      );
                      return next;
                    }),
                }}
                renderFile={(f) => (
                  <div className="rag-upload-file">
                    <input
                      type="checkbox"
                      aria-label={`${f.path} 업로드 선택`}
                      checked={!f.reason && selected.has(f.path)}
                      disabled={!!f.reason || selectionLocked}
                      onChange={(event) => {
                        const checked = event.target.checked;
                        setSelected((previous) => {
                          const next = new Set(previous);
                          if (checked) next.add(f.path);
                          else next.delete(f.path);
                          return next;
                        });
                      }}
                    />
                    <FileText size={16} />
                    <span>
                      <FilePath path={f.path} />
                      <small>{f.reason || formatBytes(f.file.size)}</small>
                    </span>
                    <b
                      className={
                        f.reason ? "excluded" : fileStatus[f.path] || ""
                      }
                    >
                      {f.reason
                        ? "제외"
                        : !selected.has(f.path)
                          ? "선택 안 함"
                          : fileStatus[f.path] === "completed"
                            ? "업로드 완료"
                            : fileStatus[f.path] === "uploading"
                              ? "업로드 중"
                              : fileStatus[f.path] === "failed"
                                ? "전송 실패"
                                : "대기 중"}
                    </b>
                  </div>
                )}
              />
            </>
          )}
        </section>
        <section className="rag-panel rag-upload-details">
          <h2>새 워크스페이스</h2>
          <label htmlFor="upload-name">이름</label>
          <input
            id="upload-name"
            maxLength={100}
            value={name}
            disabled={selectionLocked}
            placeholder="예: 제품팀 회의 자료"
            onChange={(e) => setName(e.target.value)}
          />
          <label htmlFor="upload-description">
            설명 <small>선택</small>
          </label>
          <textarea
            id="upload-description"
            maxLength={1000}
            rows={3}
            value={description}
            disabled={selectionLocked}
            placeholder="어떤 자료인지 짧게 적어 주세요."
            onChange={(e) => setDescription(e.target.value)}
          />
          <p>등록한 문서로 궁금한 내용을 검색하고, 회의 내용을 확인하세요.</p>
          <p>
            {access.role === "visitor"
              ? "내가 올린 자료는 나와 관리자만 볼 수 있습니다. 로그인 없이 이용 중인 자료는 이 브라우저에서 다시 열 수 있습니다."
              : "등록한 문서는 이 워크스페이스의 이용자와 공유됩니다."}{" "}
            내 기기의 원본 파일이 변경되면 다시 등록해 주세요.
          </p>
          {!!files.length && selection?.error && (
            <div role="alert" className="rag-alert">
              {selection.error}
            </div>
          )}
          {(busy || retry || created) && (
            <div
              className="rag-upload-progress"
              role="status"
              aria-live="polite"
            >
              <div>
                <strong>
                  {created
                    ? "업로드 완료"
                    : committing
                      ? "자료 등록 중"
                      : `${percent}% 전송`}
                </strong>
                <span>
                  {done} / {selection?.accepted.length}개
                </span>
              </div>
              <progress
                max={100}
                value={percent}
                aria-label="폴더 전송 진행률"
              />
              <small>{phase}</small>
            </div>
          )}
          {created ? (
            <button
              className="rag-primary rag-upload-submit"
              onClick={() => onCreated(created)}
            >
              <CheckCircle2 size={17} />
              워크스페이스 열기
            </button>
          ) : (
            <button
              className="rag-primary rag-upload-submit"
              disabled={
                !limits ||
                busy ||
                !name.trim() ||
                !selection?.accepted.length ||
                !!selection.error
              }
              onClick={() => void transfer()}
            >
              {busy ? (
                <Loader2 className="rag-spin" size={17} />
              ) : (
                <Upload size={17} />
              )}
              {busy ? "업로드 진행 중…" : retry ? "이어서 재시도" : "문서 등록"}
            </button>
          )}
          {(busy || retry) && (
            <button
              className="rag-secondary"
              disabled={committing}
              onClick={() => void cancel()}
            >
              <X size={16} />
              업로드 취소
            </button>
          )}
          {limits && (
            <small>
              미완료 전송은 {limits.session_hours}시간 후 자동 정리됩니다.
            </small>
          )}
        </section>
      </div>
    </div>
  );
}
