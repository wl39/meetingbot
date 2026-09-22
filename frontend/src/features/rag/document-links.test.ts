import { describe, expect, it } from "vitest";
import { documentLink } from "./document-links";
describe("workspace document links", () => {
  it("resolves Korean names and parent links within the workspace", () => {
    expect(
      documentLink("요리/README.md", "%EB%B9%84%EB%B9%94%EB%B0%A5.md"),
    ).toBe("요리/비빔밥.md");
    expect(documentLink("요리/README.md", "../가이드.md#재료")).toBe(
      "가이드.md",
    );
    expect(documentLink("요리/README.md", "./비빔밥.md")).toBe(
      "요리/비빔밥.md",
    );
  });
  it("does not treat external URLs, traversal, anchors or unsupported resources as documents", () => {
    for (const href of [
      "../../outside.md",
      "https://host/a.md",
      "//host/a.md",
      "file:///a.md",
      "javascript:alert(1)",
      "a%5Cb.md",
      "/etc/passwd",
      "image.png",
      "#heading",
      "%E0%A4%A.md",
    ])
      expect(documentLink("docs/README.md", href)).toBeNull();
  });
});
