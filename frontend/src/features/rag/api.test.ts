import { describe, expect, it } from "vitest";
import { belongsTo, locationLabel, type Evidence } from "./api";
describe("RAG response scope", () => {
  it("rejects a delayed response after switching workspace", () => {
    expect(belongsTo("workspace-b", { workspace_id: "workspace-a" })).toBe(
      false,
    );
  });
  it("accepts only the selected workspace", () => {
    expect(belongsTo("workspace-a", { workspace_id: "workspace-a" })).toBe(
      true,
    );
  });
  it("renders original line and cell locations", () => {
    expect(
      locationLabel({
        location: { type: "text", start_line: 12, end_line: 18 },
      } as Evidence),
    ).toBe("줄 12–18");
    expect(
      locationLabel({
        location: { type: "table", sheet: "운영", cell_range: "A2:D2" },
      } as Evidence),
    ).toBe("운영 · A2:D2");
  });
});
