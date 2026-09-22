export type TutorialStep =
  "welcome" | "documents" | "search" | "voice" | "file" | "done" | "dismissed";
export type TutorialState = {
  step: TutorialStep;
  source: "own" | "sample";
  workspaceId: string | null;
  workspaceName: string;
  query: string;
  voicePrompt: string;
  searched: boolean;
  recorded: boolean;
  uploaded: boolean;
};
export const initialTutorial: TutorialState = {
  step: "welcome",
  source: "own",
  workspaceId: null,
  workspaceName: "",
  query: "이 문서에서 꼭 알아야 할 내용은 무엇인가요?",
  voicePrompt: "오늘 회의에서 확인할 내용부터 이야기해 볼게요.",
  searched: false,
  recorded: false,
  uploaded: false,
};
export function tutorialStorageKey(accountId: string) {
  return `meetingbot:getting-started:v1:${accountId}`;
}
export function restoreTutorial(raw: string | null): TutorialState {
  try {
    const value = JSON.parse(raw || "null");
    if (
      !value ||
      ![
        "welcome",
        "documents",
        "search",
        "voice",
        "file",
        "done",
        "dismissed",
      ].includes(value.step)
    )
      return { ...initialTutorial };
    if (
      (value.workspaceId !== null && typeof value.workspaceId !== "string") ||
      !["own", "sample"].includes(value.source)
    )
      return { ...initialTutorial };
    const result = {
      ...initialTutorial,
      step: value.step,
      source: value.source,
      workspaceId: value.workspaceId,
    };
    for (const key of ["workspaceName", "query", "voicePrompt"] as const)
      if (typeof value[key] === "string") result[key] = value[key];
    for (const key of ["searched", "recorded", "uploaded"] as const)
      result[key] = value[key] === true;
    if (
      ["search", "voice", "file"].includes(result.step) &&
      !result.workspaceId
    )
      result.step = "documents";
    return result;
  } catch {
    return { ...initialTutorial };
  }
}
