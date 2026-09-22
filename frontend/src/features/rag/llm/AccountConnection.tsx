import { useState } from "react";
import { Check, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import type { ReadyLlmSettings } from "./useLlmSettings";

const accountStatus = {
  active: "활성",
  disabled: "비활성",
  error: "연결 오류",
  unavailable: "일시 사용 불가",
  unknown: "상태 확인 필요",
};

export default function AccountConnection({
  settings,
}: {
  settings: Pick<
    ReadyLlmSettings,
    | "codex"
    | "busy"
    | "refreshCodex"
    | "beginLogin"
    | "authUrl"
    | "callback"
    | "setCallback"
    | "completeLogin"
    | "changeAccount"
  >;
}) {
  const {
    codex,
    busy,
    refreshCodex,
    beginLogin,
    authUrl,
    callback,
    setCallback,
    completeLogin,
    changeAccount,
  } = settings;
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const loginPending = !!authUrl || codex?.login_status === "wait";
  return (
    <section className="rag-panel rag-ai-connect">
      <div>
        <h2>연결 계정</h2>
        <p>
          Meetingbot의 CLIProxyAPI에 등록된 계정입니다. Codex 앱 로그인과는
          별개입니다.
        </p>
        <p>
          {!codex
            ? "계정 정보를 불러오는 중입니다."
            : codex.error_code
              ? "계정 정보를 불러오지 못했습니다. 상태 확인을 눌러 다시 시도하세요."
              : !codex.installed
                ? "이 서버에 CLIProxyAPI가 설치되어 있지 않습니다."
                : codex.accounts?.length
                  ? `등록 ${codex.accounts.length}개 · 사용 설정 ${codex.enabled_count ?? 0}개`
                  : codex.connected
                    ? "계정이 연결되어 있지만 이메일 정보를 불러오지 못했습니다."
                    : "등록된 계정이 없습니다. ChatGPT 계정으로 로그인해 연결하세요."}
        </p>
      </div>
      <div className="rag-ai-actions">
        <button
          className="rag-secondary"
          disabled={!!busy}
          onClick={refreshCodex}
        >
          <RefreshCw size={15} />
          상태 확인
        </button>
        <button
          className="rag-primary"
          disabled={!!busy || !codex?.installed}
          onClick={beginLogin}
        >
          <ExternalLink size={15} />
          {codex?.accounts?.length ? "다른 계정 로그인" : "Codex 로그인"}
        </button>
      </div>
      {(codex?.enabled_count ?? 0) > 1 && (
        <p className="rag-ai-account-help">
          여러 계정이 활성화되어 있습니다. ‘이 계정 사용’을 누르면 해당 계정만
          사용합니다.
        </p>
      )}
      {!!codex?.accounts?.length && (
        <ul className="rag-ai-accounts" aria-label="CLIProxyAPI 연결 계정">
          {codex.accounts.map((account, index) => (
            <li key={account.id ?? index}>
              <div className="rag-ai-account-info">
                <span className="rag-ai-account-email">
                  {account.email || "이메일 정보 없음"}
                </span>
                <span className="rag-ai-account-status">
                  {accountStatus[account.status] ?? accountStatus.unknown}
                </span>
              </div>
              <div className="rag-ai-account-actions">
                {account.id && codex.selected_account_id === account.id ? (
                  <span className="rag-ai-account-selected">
                    <Check size={15} />
                    선택된 계정
                  </span>
                ) : (
                  <button
                    className="rag-secondary"
                    disabled={
                      !!busy ||
                      loginPending ||
                      !account.manageable ||
                      !account.id ||
                      !codex.revision
                    }
                    onClick={() => {
                      setDeleteId(null);
                      void changeAccount(account.id!, "select");
                    }}
                  >
                    이 계정 사용
                  </button>
                )}
                <button
                  className="rag-secondary"
                  aria-label={`${account.email || "이메일 정보 없음"} 연결 삭제`}
                  disabled={
                    !!busy ||
                    loginPending ||
                    !account.manageable ||
                    !account.id ||
                    !codex.revision
                  }
                  onClick={() => setDeleteId(account.id)}
                >
                  <Trash2 size={15} />
                  삭제
                </button>
              </div>
              {deleteId && deleteId === account.id && (
                <div
                  className="rag-ai-account-delete"
                  role="group"
                  aria-label="계정 삭제 확인"
                >
                  <p>
                    {account.email || "이 계정"}의 프록시 연결을 삭제할까요?
                    다시 사용하려면 로그인해야 합니다. ChatGPT 계정 자체는
                    삭제되지 않습니다.
                  </p>
                  {account.enabled && (
                    <p>
                      사용 중인 연결입니다. 삭제하면 이 계정으로 새 요청을
                      처리할 수 없습니다.
                    </p>
                  )}
                  <div className="rag-ai-account-actions">
                    <button
                      className="rag-secondary"
                      disabled={!!busy}
                      onClick={() => setDeleteId(null)}
                    >
                      취소
                    </button>
                    <button
                      className="rag-primary"
                      disabled={!!busy || loginPending}
                      onClick={async () => {
                        await changeAccount(account.id!, "delete");
                        setDeleteId(null);
                      }}
                    >
                      연결 삭제
                    </button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {authUrl && (
        <div className="rag-ai-login">
          <a
            href={authUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="rag-secondary"
          >
            OpenAI 로그인 창 열기 <ExternalLink size={14} />
          </a>
          <p>
            다른 계정으로 로그인하려면 위 링크를 복사해 시크릿 창에서 여세요.
            로그인 완료 후 목록에서 ‘이 계정 사용’을 눌러 변경하세요.
          </p>
          <details>
            <summary>다른 기기에서 로그인하나요?</summary>
            <p>
              로그인 뒤 localhost 연결 오류 화면이 나오면, 그 화면의 주소 전체를
              아래에 붙여넣으세요. 인증 주소는 저장하지 않습니다.
            </p>
            <label>
              로그인 완료 주소
              <input
                type="password"
                autoComplete="off"
                value={callback}
                onChange={(e) => setCallback(e.target.value)}
              />
            </label>
            <button
              className="rag-secondary"
              disabled={!!busy || !callback}
              onClick={completeLogin}
            >
              연결 완료
            </button>
          </details>
        </div>
      )}
    </section>
  );
}
