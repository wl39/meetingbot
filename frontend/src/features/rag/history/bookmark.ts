export type HistoryScope = "mine" | "all";

function storageKey(accountId: string, scope: HistoryScope) {
  return `meetingbot:last-question:${encodeURIComponent(accountId)}:${scope}`;
}

// This is a navigation hint only. The server authorizes every history read.
export function lastQuestion(accountId: string | undefined, scope: HistoryScope) {
  if (!accountId) return "";
  try {
    const id = localStorage.getItem(storageKey(accountId, scope));
    if (id && /^[a-f0-9]{32}$/.test(id)) return id;
    if (id !== null) localStorage.removeItem(storageKey(accountId, scope));
  } catch {
    // History remains available when browser storage is disabled or full.
  }
  return "";
}

export function rememberQuestion(
  accountId: string | undefined,
  scope: HistoryScope,
  questionId: string,
) {
  if (!accountId || !/^[a-f0-9]{32}$/.test(questionId)) return;
  try {
    localStorage.setItem(storageKey(accountId, scope), questionId);
  } catch {
    // The full record is already persisted on the server.
  }
}

export function forgetQuestion(
  accountId: string | undefined,
  scope: HistoryScope,
  questionId: string,
) {
  if (!accountId || lastQuestion(accountId, scope) !== questionId) return;
  try {
    localStorage.removeItem(storageKey(accountId, scope));
  } catch {
    // Storage access must never prevent opening server history.
  }
}
