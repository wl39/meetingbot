import { useState } from "react";
import { Check, Copy, Link, Network } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import { FeedbackMessage } from "../../../components/ui/FeedbackMessage";
import type { SystemStatus } from "../api";
import { useWorkspace } from "../../../workspace/context";

export default function RemoteAccessCard({
  access,
}: {
  access: SystemStatus["access"];
}) {
  const { credential } = useWorkspace();
  const [copied, setCopied] = useState("");
  const [error, setError] = useState("");
  const remoteUrl = access?.remote_url;
  async function copyAddress(includeCredential = false) {
    if (!remoteUrl) return;
    setError("");
    setCopied("");
    try {
      const address = new URL(remoteUrl);
      if (includeCredential) {
        if (!credential) return;
        address.pathname = "/";
        address.search = "";
        address.hash = `token=${encodeURIComponent(credential)}`;
      }
      await navigator.clipboard.writeText(
        includeCredential ? address.href : remoteUrl,
      );
      setCopied(includeCredential ? "private" : remoteUrl);
    } catch {
      setError(
        "주소를 복사하지 못했습니다. 아래 주소를 직접 선택해 복사하세요.",
      );
    }
  }
  return (
    <section className="management-card">
      <SectionHeading
        className="management-card-heading"
        icon={<Network size={22} />}
        title="다른 기기에서 접속"
        description="설치된 서버의 웹 주소를 다른 기기에서 열어 같은 워크스페이스를 사용하세요."
      >
        <span className="management-badge">
          {remoteUrl ? "접속 주소 설정됨" : "접속 주소 미설정"}
        </span>
      </SectionHeading>
      {remoteUrl ? (
        <>
          <div className="management-inline-action">
            <a className="management-remote-url" href={remoteUrl}>
              {remoteUrl}
            </a>
            <button
              className="management-secondary"
              onClick={() => void copyAddress()}
            >
              {copied === remoteUrl ? <Check size={17} /> : <Copy size={17} />}
              접속 주소 복사
            </button>
          </div>
          <p className="management-muted">
            {access?.kind === "tailscale"
              ? "같은 Tailscale 네트워크에 연결된 기기에서 접속하세요. 서버와 Tailscale이 실행 중이어야 합니다."
              : "이 주소에 연결할 수 있는 기기에서 접속하세요. 서버가 실행 중이어야 합니다."}{" "}
            처음 접속하는 브라우저에서는 워크스페이스 접속 키가 필요합니다.
          </p>
          {credential && (
            <div>
              <button
                className="management-secondary"
                onClick={() => void copyAddress(true)}
              >
                <Link size={17} />내 기기 접속 링크 복사
              </button>
              <p className="management-muted">
                접속 키가 포함된 링크입니다. 본인 기기에서만 사용하세요.
              </p>
            </div>
          )}
          {copied === remoteUrl && (
            <FeedbackMessage className="management-notice">
              접속 주소를 복사했습니다.
            </FeedbackMessage>
          )}
          {copied === "private" && (
            <FeedbackMessage className="management-notice">
              내 기기 접속 링크를 복사했습니다.
            </FeedbackMessage>
          )}
          {error && (
            <FeedbackMessage
              className="management-error"
              tone="error"
              onDismiss={() => setError("")}
            >
              {error}
            </FeedbackMessage>
          )}
        </>
      ) : (
        <p className="management-muted">
          외부 기기용 접속 주소가 아직 설정되지 않았습니다. 설치 안내의
          Tailscale 설정을 완료하면 이곳에서 주소를 확인할 수 있습니다.
        </p>
      )}
    </section>
  );
}
