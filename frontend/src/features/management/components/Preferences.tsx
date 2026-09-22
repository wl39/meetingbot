import { useState } from "react";
import { Type } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
export default function Preferences() {
  const [textSize, setTextSize] = useState(
    () => localStorage.getItem("meetingbot-text-size") || "standard",
  );
  const [density, setDensity] = useState(
    () => localStorage.getItem("meetingbot-density") || "standard",
  );
  function change(kind: "text-size" | "density", value: string) {
    localStorage.setItem(`meetingbot-${kind}`, value);
    if (kind === "text-size") {
      setTextSize(value);
      document.documentElement.dataset.textSize = value;
    } else {
      setDensity(value);
      document.documentElement.dataset.density = value;
    }
  }
  return (
    <section className="management-card">
      <SectionHeading
        className="management-card-heading"
        icon={<Type size={21} />}
        title="읽기 편한 화면"
        description="이 브라우저에 저장되며, 바로 적용됩니다."
      />
      <div className="management-preference-row">
        <div>
          <strong>글자 크기</strong>
          <p>대본과 설정을 편하게 읽을 수 있도록</p>
        </div>
        <div
          className="management-segmented"
          role="group"
          aria-label="글자 크기"
        >
          {[
            { value: "standard", label: "기본" },
            { value: "large", label: "크게" },
          ].map((x) => (
            <button
              key={x.value}
              aria-pressed={textSize === x.value}
              onClick={() => change("text-size", x.value)}
            >
              {x.label}
            </button>
          ))}
        </div>
      </div>
      <div className="management-preference-row">
        <div>
          <strong>화면 간격</strong>
          <p>패널 여백을 줄여 한눈에 더 많은 정보 보기</p>
        </div>
        <div
          className="management-segmented"
          role="group"
          aria-label="화면 간격"
        >
          {[
            { value: "standard", label: "기본" },
            { value: "compact", label: "촘촘하게" },
          ].map((x) => (
            <button
              key={x.value}
              aria-pressed={density === x.value}
              onClick={() => change("density", x.value)}
            >
              {x.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
