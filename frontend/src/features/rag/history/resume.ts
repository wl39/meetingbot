// Browser references only: questions, answers and credentials stay out of this cache.
type Resume = { workspaceId: string; questionId: string | null };
const prefix = "meetingbot:rag-resume:v1:";
const isId = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{32}$/.test(value);

export function readResume(accountId?: string): Resume | null {
  if (!accountId) return null;
  try {
    const value = JSON.parse(localStorage.getItem(prefix + accountId) || "null");
    if (!value || !isId(value.workspaceId)) return null;
    return {
      workspaceId: value.workspaceId,
      questionId: isId(value.questionId) ? value.questionId : null,
    };
  } catch {
    return null;
  }
}

export function rememberWorkspace(accountId: string | undefined, workspaceId: string | null) {
  const previous = readResume(accountId);
  writeResume(accountId, workspaceId ? {
    workspaceId,
    questionId: previous?.workspaceId === workspaceId ? previous.questionId : null,
  } : null);
}

export function rememberQuestion(accountId: string | undefined, workspaceId: string, questionId: string | null) {
  if (readResume(accountId)?.workspaceId !== workspaceId) return;
  writeResume(accountId, { workspaceId, questionId });
}

function writeResume(accountId: string | undefined, value: Resume | null) {
  if (!accountId) return;
  try {
    if (value) localStorage.setItem(prefix + accountId, JSON.stringify(value));
    else localStorage.removeItem(prefix + accountId);
  } catch {
    // Storage can be disabled or full; server history remains available.
  }
}
