export type SettingsPath =
  | "/settings"
  | "/settings/speech"
  | "/settings/rag"
  | "/settings/ai"
  | "/settings/updates"
  | "/settings/access";
export type RagPath =
  "/rag" | "/rag/settings" | "/rag/history" | "/rag/history/all";
export type WorkspacePath = "/" | "/live" | RagPath | SettingsPath;
export type SttMode = "file" | "live";
export type WorkspaceView = SttMode | "rag" | "settings";

export function workspacePath(pathname: string): WorkspacePath {
  if (pathname === "/live") return "/live";
  if (pathname === "/rag/settings") return "/settings/ai";
  if (pathname === "/rag/history" || pathname === "/rag/history/all")
    return pathname;
  if (
    [
      "/settings",
      "/settings/speech",
      "/settings/rag",
      "/settings/ai",
      "/settings/updates",
      "/settings/access",
    ].includes(pathname)
  )
    return pathname as SettingsPath;
  if (pathname.startsWith("/settings/")) return "/settings";
  return pathname === "/rag" || pathname.startsWith("/rag/") ? "/rag" : "/";
}

export function workspaceView(path: WorkspacePath): WorkspaceView {
  if (path.startsWith("/settings") || path === "/rag/settings")
    return "settings";
  return path.startsWith("/rag") ? "rag" : path === "/live" ? "live" : "file";
}

export function canNavigate(path: WorkspacePath, busyMode: SttMode | null) {
  const next = workspaceView(path);
  return (
    !busyMode || next === "rag" || next === "settings" || next === busyMode
  );
}
