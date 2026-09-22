import { useState } from "react";
import { api } from "./api";
export function SpeakerEditor({
  sid,
  speakers,
  refresh,
  onError,
}: {
  sid: string;
  speakers: Record<string, string>;
  refresh: () => void;
  onError: (s: string) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState("");
  return (
    <div className="speaker-manager">
      <div className="speaker-manager-heading">
        <strong>화자 이름</strong>
        <span>이름을 바꾸면 같은 화자의 모든 발언에 적용됩니다.</span>
      </div>
      <div className="speaker-list">
        <button
          className="add-speaker"
          onClick={async () => {
            try {
              await api(`/sessions/${sid}/speakers`, {
                method: "POST",
                body: JSON.stringify({
                  name: `화자 ${String.fromCharCode(65 + Object.keys(speakers).length)}`,
                }),
              });
              refresh();
            } catch (e) {
              onError(String(e));
            }
          }}
        >
          + 화자 추가
        </button>
        {Object.entries(speakers).map(([id, label], i) => (
          <div key={id} className="speaker-chip">
            <span className={`speaker-avatar color-${i % 8}`}>
              {String.fromCharCode(65 + i)}
            </span>
            {editing === id ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  try {
                    await api(`/sessions/${sid}/speakers/${id}`, {
                      method: "PATCH",
                      body: JSON.stringify({ name }),
                    });
                    setEditing(null);
                    refresh();
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                <input
                  aria-label="화자 표시 이름"
                  autoFocus
                  maxLength={80}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                <button disabled={!name.trim()}>전체 적용</button>
                <button type="button" onClick={() => setEditing(null)}>
                  취소
                </button>
              </form>
            ) : (
              <button
                title={`${String.fromCharCode(65 + i)} 화자의 모든 발언 이름 변경`}
                onClick={() => {
                  setEditing(id);
                  setName(label);
                }}
              >
                {label} <span className="speaker-edit-hint">이름 변경</span>
              </button>
            )}
          </div>
        ))}
        {!Object.keys(speakers).length && (
          <span className="speaker-pending">
            발언자를 확인하면 이름을 지정할 수 있습니다.
          </span>
        )}
      </div>
    </div>
  );
}
