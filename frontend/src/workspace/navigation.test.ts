import { describe, expect, it } from "vitest";
import { canNavigate, workspacePath, workspaceView } from "./navigation";

describe("workspace navigation", () => {
  it("preserves RAG settings and direct transcription routes", () => {
    expect(workspacePath("/rag/settings")).toBe("/settings/ai");
    expect(workspaceView(workspacePath("/rag/settings"))).toBe("settings");
    expect(workspacePath("/settings/rag")).toBe("/settings/rag");
    expect(workspaceView("/settings/speech")).toBe("settings");
    expect(workspacePath("/settings/unknown")).toBe("/settings");
    expect(workspaceView(workspacePath("/live"))).toBe("live");
    expect(workspaceView(workspacePath("/"))).toBe("file");
    expect(workspacePath("/rag/legacy")).toBe("/rag");
    expect(workspacePath("/rag/history")).toBe("/rag/history");
    expect(workspacePath("/rag/history/all")).toBe("/rag/history/all");
    expect(workspaceView("/rag/history/all")).toBe("rag");
    expect(workspacePath("/ragged")).toBe("/");
  });
  it("lets a recording continue while opening RAG and returning", () => {
    expect(canNavigate("/rag", "live")).toBe(true);
    expect(canNavigate("/rag/settings", "live")).toBe(true);
    expect(canNavigate("/settings/speech", "live")).toBe(true);
    expect(canNavigate("/live", "live")).toBe(true);
    expect(canNavigate("/", "live")).toBe(false);
  });
  it("lets an upload continue while opening RAG, without replacing its input mode", () => {
    expect(canNavigate("/rag", "file")).toBe(true);
    expect(canNavigate("/settings/rag", "file")).toBe(true);
    expect(canNavigate("/", "file")).toBe(true);
    expect(canNavigate("/live", "file")).toBe(false);
    expect(canNavigate("/live", null)).toBe(true);
  });
});
