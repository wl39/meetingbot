import { describe, expect, it } from "vitest";
import { initialTutorial, restoreTutorial, tutorialStorageKey } from "./state";

describe("first visit and resume", () => {
  it("starts new visitors at the document question", () => {
    expect(restoreTutorial(null).step).toBe("welcome");
    expect(restoreTutorial("not json").step).toBe("welcome");
  });
  it("preserves dismissal and completed work on return", () => {
    expect(
      restoreTutorial(JSON.stringify({ ...initialTutorial, step: "dismissed" }))
        .step,
    ).toBe("dismissed");
    const saved = {
      ...initialTutorial,
      step: "voice",
      workspaceId: "my-documents",
      searched: true,
    };
    expect(restoreTutorial(JSON.stringify(saved))).toEqual(saved);
  });
  it("requires a document selection before resuming later steps", () => {
    expect(
      restoreTutorial(JSON.stringify({ ...initialTutorial, step: "file" }))
        .step,
    ).toBe("documents");
  });
  it("isolates accounts and rejects invalid saved values", () => {
    expect(tutorialStorageKey("one")).not.toBe(tutorialStorageKey("two"));
    expect(
      restoreTutorial(JSON.stringify({ ...initialTutorial, step: "injected" })),
    ).toEqual(initialTutorial);
    expect(
      restoreTutorial(
        JSON.stringify({ ...initialTutorial, query: {}, searched: "true" }),
      ),
    ).toEqual(initialTutorial);
  });
});
