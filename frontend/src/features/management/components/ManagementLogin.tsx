import { useState } from "react";
import { KeyRound } from "lucide-react";

export default function ManagementLogin({
  connect,
}: {
  connect: (key: string) => void;
}) {
  const [key, setKey] = useState("");
  return (
    <section className="management-card management-login">
      <KeyRound size={28} />
      <h2>워크스페이스에 로그인</h2>
      <p>설치할 때 받은 접속 키로 모델과 설정을 관리하세요.</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          connect(key);
          setKey("");
        }}
      >
        <input
          aria-label="관리 접속 키"
          type="password"
          autoComplete="off"
          placeholder="워크스페이스 접속 키"
          value={key}
          onChange={(event) => setKey(event.target.value)}
        />
        <button className="management-primary" disabled={!key.trim()}>
          로그인
        </button>
      </form>
    </section>
  );
}
