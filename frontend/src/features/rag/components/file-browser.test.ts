import { describe, expect, it } from "vitest";
import { directoryEntries, sortFiles } from "./file-browser";

describe("directory browsing", () => {
  const files = [
    { path: "팀/회의/정책.md" },
    { path: "팀/예산.xlsx", attention: true },
    { path: "팀별/다른.txt" },
    { path: "읽어보기.md" },
  ];
  it("shows direct children and counts nested files without mixing sibling prefixes", () => {
    const root = directoryEntries(files, "");
    expect(root.folders.map((f) => [f.path, f.files.length])).toEqual([
      ["팀", 2],
      ["팀별", 1],
    ]);
    expect(root.files.map((f) => f.path)).toEqual(["읽어보기.md"]);
    const team = directoryEntries(files, "팀");
    expect(team.folders.map((f) => f.path)).toEqual(["팀/회의"]);
    expect(team.files.map((f) => f.path)).toEqual(["팀/예산.xlsx"]);
    expect(directoryEntries(files, "팀/회의").files[0].path).toBe(
      "팀/회의/정책.md",
    );
  });
  it("puts issues first in flat view without mutating original file order", () => {
    expect(sortFiles(files)[0].path).toBe("팀/예산.xlsx");
    expect(files[0].path).toBe("팀/회의/정책.md");
  });
});
