import { createContext, useContext } from "react";
import type {
  RagPath,
  SttMode,
  WorkspacePath,
  WorkspaceView,
} from "./navigation";
import type { Access } from "./access";

type Navigation = {
  access: Access;
  view: WorkspaceView;
  sttMode: SttMode;
  ragPath: RagPath;
  busyMode: SttMode | null;
  setBusyMode: (mode: SttMode | null) => void;
  navigate: (path: WorkspacePath) => void;
  credential: string;
  connect: (key: string) => void;
};
export const WorkspaceContext = createContext<Navigation | null>(null);
export function useWorkspace() {
  const value = useContext(WorkspaceContext);
  if (!value) throw new Error("Workspace provider is required");
  return value;
}
