import { Loader2 } from "lucide-react";
import type { SearchResult } from "../api";

export function questionPending(status?: string) {
  return status === "queued" || status === "processing";
}

export default function QuestionProgress({ result }: { result: SearchResult }) {
  return (
    <div className="rag-answer" role="status" aria-live="polite">
      <h3>
        <Loader2 size={18} className="rag-spin" />
        {result.status === "queued"
          ? "질문이 접수되었습니다 · 처리 대기 중"
          : "자료 확인 · 답변 생성 중"}
      </h3>
      <p>{result.query}</p>
      <p>
        {result.status === "queued"
          ? "먼저 접수된 요청을 처리하고 있습니다. 차례가 되면 자동으로 시작합니다."
          : "관련 문서를 확인하고 답변을 작성하고 있습니다."}
      </p>
      <p>
        다른 질문을 하거나 화면을 이동해도 처리는 계속됩니다. 결과는 내 질문
        기록에 저장됩니다.
      </p>
    </div>
  );
}
