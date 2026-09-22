import { useEffect, useState } from "react";
import { Settings2, RefreshCw } from "lucide-react";
import { api as ragApi, RagApiError } from "../rag/api";
import type { MeetingPolicy } from "./jobs";

export const numericBounds = {
  priority_response_target_seconds: [3, 120],
  filter_timeout_seconds: [1, 15],
  generation_timeout_seconds: [1, 60],
  context_wait_seconds: [0, 5],
  recovery_seconds: [0, 30],
  recovery_ratio: [0, 0.99],
  pressure_ratio: [0, 0.99],
  protect_ratio: [0, 0.99],
} as const;
export const scopeLength = (policy: MeetingPolicy) => {
  const lists = [
    policy.scope_profile.included_topics,
    policy.scope_profile.excluded_topics,
    policy.scope_profile.aliases,
  ];
  // Match the server's Unicode JSON character budget, including keys and separators.
  return (
    Array.from(JSON.stringify(policy.scope_profile)).length +
    7 +
    lists.reduce((sum, values) => sum + Math.max(0, values.length - 1), 0)
  );
};
export function policyError(policy: MeetingPolicy): string {
  if (!(
    Number.isInteger(policy.priority_response_target_seconds) &&
    policy.priority_response_target_seconds >= 3 &&
    policy.priority_response_target_seconds <= 120
  ))
    return "우선큐 응답 목표는 3~120초 사이로 입력하세요.";
  if (!(
    0 <= policy.recovery_ratio &&
    policy.recovery_ratio < policy.pressure_ratio &&
    policy.pressure_ratio < policy.protect_ratio &&
    policy.protect_ratio < 1
  ))
    return "복구 비율 < 강화 비율 < 집중 비율 순서로 0~1 사이 값을 입력하세요.";
  if (
    Object.entries(numericBounds).some(([key, [min, max]]) => {
      const value = policy[key as keyof typeof numericBounds];
      return !Number.isFinite(value) || value < min || value > max;
    })
  )
    return "분류 제한 1~15초, 답변 제한 1~60초, 문맥 대기 0~5초, 복구 관찰 0~30초 범위를 확인하세요.";
  if (policy.scope_profile.description.length > 600)
    return "업무 대상 설명은 600자 이내로 입력하세요.";
  const lists = [
    policy.scope_profile.included_topics,
    policy.scope_profile.excluded_topics,
    policy.scope_profile.aliases,
  ];
  if (
    lists.some(
      (values) =>
        values.length > 12 ||
        values.some((value) => !value.trim() || value.length > 60),
    )
  )
    return "주제와 별칭은 각각 12개 이하, 각 항목은 1~60자로 입력하세요.";
  if (
    policy.filter_model.length > 200 ||
    /[\x00-\x1f]/.test(policy.filter_model)
  )
    return "분류 모델 이름은 제어문자 없이 200자 이내로 입력하세요.";
  if (scopeLength(policy) > 1600)
    return "업무 범위 전체를 합쳐 1,600자 이내로 입력하세요.";
  return "";
}
export const policyList = (value: string) =>
  value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);

export function MeetingPolicyPanel({
  workspaceId,
  superadmin,
}: {
  workspaceId: string;
  superadmin: boolean;
}) {
  const [policy, setPolicy] = useState<MeetingPolicy | null>(null);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setPolicy(null);
    setError("");
    setMessage("");
    setDirty(false);
    ragApi<MeetingPolicy>(
      `/workspaces/${encodeURIComponent(workspaceId)}/meeting/policy`,
      undefined,
      "GET",
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setPolicy(value);
      })
      .catch((caught) => {
        if (!controller.signal.aborted)
          setError(String(caught instanceof Error ? caught.message : caught));
      });
    return () => controller.abort();
  }, [workspaceId, reload]);
  function update(next: MeetingPolicy) {
    setPolicy(next);
    setDirty(true);
    setMessage("");
  }
  async function save() {
    if (!policy) return;
    const invalid = policyError(policy);
    if (invalid) {
      setError(invalid);
      return;
    }
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const { version, ...fields } = policy;
      const saved = await ragApi<MeetingPolicy>(
        `/workspaces/${encodeURIComponent(workspaceId)}/meeting/policy`,
        { ...fields, expected_version: version },
        "PUT",
      );
      setPolicy(saved);
      setDirty(false);
      setMessage(
        "설정을 저장했습니다. 새로 접수한 작업부터 적용하며, 기존 작업의 마감은 유지됩니다.",
      );
    } catch (caught) {
      setError(
        caught instanceof RagApiError && caught.status === 409
          ? "다른 관리자가 설정을 변경했습니다. 다시 불러온 뒤 수정해 주세요."
          : String(caught instanceof Error ? caught.message : caught),
      );
    } finally {
      setSaving(false);
    }
  }
  const numeric = (
    key: keyof typeof numericBounds,
    label: string,
    step = "1",
  ) =>
    policy && (
      <label key={key}>
        {label}
        <input
          type="number"
          step={step}
          min={numericBounds[key][0]}
          max={numericBounds[key][1]}
          value={policy[key]}
          onChange={(e) => update({ ...policy, [key]: Number(e.target.value) })}
        />
      </label>
    );
  return (
    <details className="meeting-policy">
      <summary>
        <Settings2 size={15} /> 관리자 · 분류와 응답 설정
      </summary>
      {error && (
        <p role="alert" className="meeting-policy-error">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {!policy ? (
        <button onClick={() => setReload((v) => v + 1)}>
          <RefreshCw size={13} /> 설정 불러오기
        </button>
      ) : (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={saving}>
            <legend>우선큐 응답 목표</legend>
            {numeric("priority_response_target_seconds", "응답 목표 N (초)")}
            <p>
              필터 판단부터 최종 답변까지의 목표입니다. 외부 모델 지연 시 초과
              사실을 표시하며, N초 이내의 완성 답변을 보장하지 않습니다.
            </p>
            <details>
              <summary>처리 강화·복구 설정</summary>
              <div className="meeting-policy-grid">
                {numeric("pressure_ratio", "우선큐 강화 비율", "0.05")}
                {numeric("protect_ratio", "우선큐 집중 비율", "0.05")}
                {numeric("recovery_ratio", "보조큐 복구 비율", "0.05")}
                {numeric("recovery_seconds", "복구 관찰 (초)")}
                {numeric("context_wait_seconds", "후속 문맥 대기 (초)", "0.5")}
                {numeric("filter_timeout_seconds", "분류 제한시간 (초)")}
                {numeric("generation_timeout_seconds", "답변 제한시간 (초)")}
              </div>
              <p>
                비율은 응답 목표 N 중 경과한 시간입니다. 집중 모드에서는
                보조큐의 다음 단계 실행을 멈춥니다.
              </p>
            </details>
            <label>
              분류 모델
              <input
                maxLength={200}
                value={policy.filter_model}
                disabled={!superadmin}
                placeholder="비어 있으면 기본 모델 사용"
                onChange={(e) =>
                  update({ ...policy, filter_model: e.target.value })
                }
              />
            </label>
            <p>
              {superadmin
                ? "운영 관리자만 변경할 수 있습니다. "
                : "모델 변경은 운영 관리자에게 요청하세요. "}
              빈 값은 기본 모델을 사용합니다. 별도 모델의 비용·속도는 실제
              호출로 확인해야 합니다.
            </p>
          </fieldset>
          <fieldset disabled={saving}>
            <legend>우리 RAG의 업무 범위</legend>
            <p>
              저장 형식을 포함해 {scopeLength(policy).toLocaleString()} /
              1,600자
            </p>
            <label>
              업무 대상과 범위
              <textarea
                rows={3}
                maxLength={600}
                placeholder="예: 우리 서비스의 운영·개발 서버, 로그와 배포 정책"
                value={policy.scope_profile.description}
                onChange={(e) =>
                  update({
                    ...policy,
                    scope_profile: {
                      ...policy.scope_profile,
                      description: e.target.value,
                    },
                  })
                }
              />
            </label>
            {(
              [
                ["included_topics", "포함할 주제"],
                ["excluded_topics", "제외할 주제"],
                ["aliases", "서비스명·별칭"],
              ] as const
            ).map(([key, label]) => (
              <label key={key}>
                {label} (한 줄에 하나 · 최대 12개, 각 60자)
                <textarea
                  rows={3}
                  value={policy.scope_profile[key].join("\n")}
                  onChange={(e) =>
                    update({
                      ...policy,
                      scope_profile: {
                        ...policy.scope_profile,
                        [key]: e.target.value.split("\n"),
                      },
                    })
                  }
                  onBlur={() =>
                    update({
                      ...policy,
                      scope_profile: {
                        ...policy.scope_profile,
                        [key]: policyList(policy.scope_profile[key].join("\n")),
                      },
                    })
                  }
                />
              </label>
            ))}
            <p>
              질문이어도 업무 범위 밖이면 2점입니다. 대상이 불분명하면 앞뒤
              문맥으로 확인하고 분류를 보류합니다.
            </p>
          </fieldset>
          <div className="meeting-policy-actions">
            <button
              type="submit"
              className="primary"
              disabled={saving || !dirty}
            >
              {saving ? "저장 중…" : "설정 저장"}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={() => setReload((v) => v + 1)}
            >
              다시 불러오기
            </button>
          </div>
        </form>
      )}
    </details>
  );
}
