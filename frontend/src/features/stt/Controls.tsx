import { modelReady, type Health, type Options } from "./api";
import { useWorkspace } from "../../workspace/context";
export function Controls({
  value,
  onChange,
  disabled,
  health,
}: {
  value: Options;
  onChange: (v: Options) => void;
  disabled: boolean;
  health: Health | null;
}) {
  const { access } = useWorkspace();
  const needsModel = !!health && !modelReady(health, value.model);
  return (
    <>
      <div className="controls">
        <label>
          전사 방식
          <select
            value={value.model}
            disabled={disabled}
            onChange={(e) =>
              onChange({ ...value, model: e.target.value as Options["model"] })
            }
          >
            <option value="small">
              빠르게 전사{health?.default_model === "small" ? " · 기본" : ""}
            </option>
            <option value="large-v3-turbo">
              정확도 우선
              {health?.default_model === "large-v3-turbo" ? " · 기본" : ""}
            </option>
          </select>
        </label>
        <label>
          화자 수
          <select
            disabled={disabled}
            value={value.num_speakers || ""}
            onChange={(e) =>
              onChange({
                ...value,
                num_speakers: Number(e.target.value) || null,
              })
            }
          >
            <option value="">자동 감지 · 1–8명</option>
            {Array.from({ length: 8 }, (_, i) => (
              <option key={i + 1} value={i + 1}>
                {i + 1}명
              </option>
            ))}
          </select>
        </label>
      </div>
      {needsModel && (
        <div className="model-readiness" role="status">
          <span>
            {health?.management_busy
              ? "회의 기록 서비스를 준비하고 있습니다. 잠시 후 이용해 주세요."
              : "선택한 기록 방식을 현재 이용할 수 없습니다. 다른 방식을 선택하거나 관리자에게 문의해 주세요."}
          </span>
        </div>
      )}
      {!access.demo && (
        <label className="checkbox">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value.retain_audio}
            onChange={(e) =>
              onChange({ ...value, retain_audio: e.target.checked })
            }
          />
          원음 보관
        </label>
      )}
    </>
  );
}
