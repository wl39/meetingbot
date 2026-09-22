import { useEffect, useState } from "react";
import { accessHeaders, roleLabels, type Role } from "../../workspace/access";
import { useWorkspace } from "../../workspace/context";

type AccessKey = {
  id: string;
  label: string;
  role: Role;
  created: number;
  revoked: number | null;
};
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const r = await fetch("/api/access" + path, {
    method,
    headers: { ...accessHeaders(), "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok)
    throw new Error(
      "접속 키를 처리하지 못했습니다. 슈퍼관리자 권한과 연결을 확인하세요.",
    );
  return r.json();
}
export default function AccessSection() {
  const { access } = useWorkspace();
  const [keys, setKeys] = useState<AccessKey[]>([]);
  const [label, setLabel] = useState("");
  const [role, setRole] = useState<Role>("visitor");
  const [issued, setIssued] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reload = () =>
    request<{ keys: AccessKey[] }>("/keys").then((r) => setKeys(r.keys));
  useEffect(() => {
    void reload().catch((e) => setError(String(e)));
  }, []);
  return (
    <section className="management-card access-settings">
      <h2>접속 키와 권한</h2>
      <p>
        관리자는 공유 자료를 관리하고, 운영 관리자는 모델·AI 설정과 접속 키도
        관리할 수 있습니다. 녹음과 음성 파일 기록은 역할에 관계없이 본인만
        확인할 수 있습니다.
      </p>
      <p>
        {access.demo
          ? "공개 데모가 실행 중입니다. 키 없이 들어오면 방문자로 연결됩니다."
          : access.keyless
            ? "키 없이 방문자로 접속할 수 있습니다. 관리 기능은 관리자 키로 로그인하세요."
            : "발급된 접속 키로 로그인해야 사용할 수 있습니다."}
      </p>
      {error && (
        <p className="management-error" role="alert">
          {error}
        </p>
      )}
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          setIssued("");
          try {
            const key = await request<{ key: string }>("/keys", "POST", {
              label,
              role,
            });
            setIssued(key.key);
            setLabel("");
            await reload();
          } catch (error) {
            setError(String(error));
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          키 이름
          <input
            required
            maxLength={80}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="예: 데모 운영 담당"
          />
        </label>
        <label>
          권한
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
          >
            {Object.entries(roleLabels).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
        </label>
        <button className="primary" disabled={busy || !label.trim()}>
          접속 키 발급
        </button>
      </form>
      {issued && (
        <div className="management-issued-key" role="status">
          <strong>새 접속 키 · 이 화면에서 한 번만 표시됩니다</strong>
          <input
            aria-label="새 접속 키"
            readOnly
            type="text"
            value={issued}
            onFocus={(e) => e.target.select()}
          />
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(issued);
              } catch {
                setError("키를 선택해 직접 복사해 주세요.");
              }
            }}
          >
            복사
          </button>
          <button onClick={() => setIssued("")}>표시 닫기</button>
        </div>
      )}
      <div className="access-key-list">
        {keys.map((key) => (
          <div key={key.id}>
            <span>
              <strong>{key.label}</strong>
              <small>
                {roleLabels[key.role]} · {key.revoked ? "폐기됨" : "사용 가능"}
              </small>
            </span>
            {!key.revoked && (
              <button
                disabled={busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await request(`/keys/${key.id}`, "DELETE");
                    await reload();
                  } catch (e) {
                    setError(String(e));
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                키 폐기
              </button>
            )}
          </div>
        ))}
      </div>
      {!keys.length && (
        <p>
          아직 발급한 키가 없습니다. 기존 설치 키는 슈퍼관리자 키로 유지됩니다.
        </p>
      )}
    </section>
  );
}
