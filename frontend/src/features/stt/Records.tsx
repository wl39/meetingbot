import { useEffect, useId, useRef } from "react";
import {
  Clock3,
  FileAudio,
  LoaderCircle,
  Mic,
  Search,
  Trash2,
  X,
} from "lucide-react";
import "./records.css";

export type RecordSummary = {
  id: string;
  mode: string;
  state: string;
  created_at: number;
};

export function recordName(record: Pick<RecordSummary, "mode" | "created_at">) {
  const date = new Date(record.created_at * 1000).toLocaleString("ko-KR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${record.mode === "file" ? "파일 전사" : "마이크 녹음"} · ${date}`;
}

export function RecordsList({
  records,
  selectedId,
  query,
  onQuery,
  busy,
  onSelect,
  onDelete,
}: {
  records: RecordSummary[];
  selectedId?: string;
  query: string;
  onQuery: (value: string) => void;
  busy: boolean;
  onSelect: (id: string) => void;
  onDelete: (record: RecordSummary) => void;
}) {
  const visible = records.filter((record) =>
    recordName(record)
      .toLocaleLowerCase("ko-KR")
      .includes(query.trim().toLocaleLowerCase("ko-KR")),
  );
  return (
    <div className="records-panel">
      {!!records.length && (
        <label className="record-search">
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            aria-label="내 기록 검색"
            placeholder="종류 또는 날짜로 검색"
            value={query}
            onChange={(event) => onQuery(event.target.value)}
          />
        </label>
      )}
      <div className="record-list">
        {!records.length ? (
          <p className="records-empty">
            녹음한 회의가 여기에 모입니다. 첫 번째 기록을 만들어 보세요.
          </p>
        ) : !visible.length ? (
          <p className="records-empty">검색한 기록이 없습니다.</p>
        ) : (
          visible.map((record) => (
            <div
              key={record.id}
              className={`record-item ${selectedId === record.id ? "selected" : ""}`}
            >
              <button
                className="record-open"
                aria-current={selectedId === record.id ? "true" : undefined}
                disabled={busy}
                onClick={() => onSelect(record.id)}
              >
                {record.mode === "file" ? (
                  <FileAudio size={18} />
                ) : (
                  <Mic size={18} />
                )}
                <span>
                  {record.mode === "file" ? "파일 전사" : "마이크 녹음"}
                  <small>{recordName(record).split(" · ")[1]}</small>
                </span>
              </button>
              <button
                className="record-delete"
                aria-label={`${recordName(record)} 삭제`}
                title={
                  busy
                    ? "녹음 또는 업로드를 마친 후 삭제할 수 있습니다."
                    : "기록 삭제"
                }
                disabled={busy}
                onClick={() => onDelete(record)}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))
        )}
      </div>
      {busy && (
        <p className="records-help">
          녹음 또는 업로드를 마친 후 기록을 선택하거나 삭제할 수 있습니다.
        </p>
      )}
    </div>
  );
}

function useRecordDialog(onClose: () => void) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement as HTMLElement | null;
    dialog.showModal();
    return () => {
      dialog.close();
      if (trigger?.isConnected) trigger.focus();
    };
  }, []);
  return {
    ref,
    onCancel: (event: React.SyntheticEvent) => {
      event.preventDefault();
      onClose();
    },
  };
}

export function RecordsDialog({
  onClose,
  children,
}: {
  onClose: () => void;
  children: React.ReactNode;
}) {
  const id = useId();
  const dialog = useRecordDialog(onClose);
  return (
    <dialog {...dialog} className="records-dialog" aria-labelledby={id}>
      <header className="records-dialog-heading">
        <h2 id={id}>
          <Clock3 size={20} /> 내 기록
        </h2>
        <button
          className="record-dialog-close"
          aria-label="내 기록 닫기"
          onClick={onClose}
          autoFocus
        >
          <X size={20} />
        </button>
      </header>
      <div className="records-dialog-body">{children}</div>
    </dialog>
  );
}

export function DeleteRecordDialog({
  name,
  busy,
  error,
  onClose,
  onConfirm,
}: {
  name: string;
  busy: boolean;
  error: string;
  onClose: () => void;
  onConfirm: () => void;
}) {
  const id = useId();
  const dialog = useRecordDialog(() => {
    if (!busy) onClose();
  });
  return (
    <dialog
      {...dialog}
      className="records-dialog record-confirm-dialog"
      aria-labelledby={`${id}-title`}
      aria-describedby={`${id}-description`}
    >
      <header className="records-dialog-heading">
        <h2 id={`${id}-title`}>기록을 삭제할까요?</h2>
        <button
          className="record-dialog-close"
          aria-label="삭제 창 닫기"
          disabled={busy}
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      <div className="records-dialog-body">
        <p className="record-confirm-name">{name}</p>
        <p id={`${id}-description`}>
          대본과 이 기록에 저장된 음성이 삭제됩니다. 삭제한 기록은 복구할 수
          없습니다.
        </p>
        {error && (
          <p className="record-confirm-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <footer className="records-dialog-footer">
        <button disabled={busy} onClick={onClose} autoFocus>
          취소
        </button>
        <button
          className="record-confirm-delete"
          disabled={busy}
          onClick={onConfirm}
        >
          {busy ? (
            <LoaderCircle className="spin" size={16} />
          ) : (
            <Trash2 size={16} />
          )}
          {busy ? "삭제 중…" : "삭제"}
        </button>
      </footer>
    </dialog>
  );
}
