import { useEffect, useState } from "react";
import { Palette } from "lucide-react";
import { SectionHeading } from "../../../components/ui/SectionHeading";
import {
  applyTheme,
  DEFAULT_THEME,
  useThemeColor,
  validColor,
} from "../../../workspace/theme";
import { systemApi } from "../api";

const presets = [
  ["서재 오렌지", DEFAULT_THEME],
  ["포레스트", "#225e4b"],
  ["오션 블루", "#2563eb"],
  ["바이올렛", "#7c3aed"],
  ["로즈", "#be3455"],
];
export default function ThemeSettings() {
  const saved = useThemeColor();
  const [color, setColor] = useState(saved);
  const [pending, setPending] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    setColor(saved);
  }, [saved]);
  async function save() {
    setPending(true);
    setNotice("");
    setError("");
    try {
      const value = await systemApi<{ color: string }>("/theme", { color });
      applyTheme(value.color);
      setNotice("전체 테마색을 저장했습니다. 방문자 화면에도 적용됩니다.");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "테마색을 저장하지 못했습니다.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <section className="management-card theme-settings">
      <SectionHeading
        className="management-card-heading"
        icon={<Palette size={21} />}
        title="전체 테마색"
        description="버튼, 메뉴, 배경과 강조색을 모든 이용자에게 동일하게 적용합니다."
      />
      <div className="theme-presets" role="group" aria-label="테마색 프리셋">
        {presets.map(([label, value]) => (
          <button
            key={value}
            disabled={pending}
            aria-pressed={color.toLowerCase() === value}
            onClick={() => {
              setColor(value);
              setNotice("");
            }}
          >
            <span className="theme-swatch" style={{ background: value }} />
            {label}
          </button>
        ))}
      </div>
      <div className="theme-color-row">
        <label htmlFor="theme-color-picker">직접 선택</label>
        <input
          id="theme-color-picker"
          type="color"
          value={validColor(color) ? color : saved}
          disabled={pending}
          onChange={(e) => {
            setColor(e.target.value);
            setNotice("");
          }}
        />
        <input
          aria-label="테마색 코드"
          value={color}
          maxLength={7}
          spellCheck={false}
          disabled={pending}
          onChange={(e) => {
            setColor(e.target.value);
            setNotice("");
          }}
        />
        <button
          className="management-primary"
          disabled={
            pending || !validColor(color) || color.toLowerCase() === saved
          }
          onClick={() => void save()}
        >
          {pending ? "저장 중…" : "전체 화면에 적용"}
        </button>
      </div>
      <p>
        대표 이미지의 따뜻한 주황빛이 기본 테마입니다. 밝은 색은 글자가 잘
        보이도록 조정됩니다.
      </p>
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
