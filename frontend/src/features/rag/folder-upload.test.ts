import { describe, expect, it } from "vitest";
import { selectFolder, type UploadLimits } from "./folder-upload";
const limits: UploadLimits = {
  extensions: [".md", ".txt", ".csv", ".tsv", ".xlsx"],
  max_files: 2000,
  max_file_bytes: 100,
  max_total_bytes: 200,
  max_depth: 11,
  session_hours: 24,
};
const file = (path: string, size = 10) =>
  ({
    name: path.split("/").pop()!,
    webkitRelativePath: path,
    size,
  }) as File;
describe("folder selection before transfer", () => {
  it("uploads only checked files and recalculates size and directory limits", () => {
    const files = [
      file("자료/운영/정책.md", 80),
      file("자료/개발/정책.md", 80),
      file("자료/.env"),
    ];
    const selected = selectFolder(
      files,
      { ...limits, max_total_bytes: 100, max_files: 2 },
      new Set(["개발/정책.md", ".env"]),
    );
    expect(selected.accepted.map((f) => f.path)).toEqual(["개발/정책.md"]);
    expect(selected.bytes).toBe(80);
    expect(selected.error).toBe("");
    expect(selected.picked).toHaveLength(3);
    expect(selectFolder(files, limits, new Set()).error).toContain(
      "파일을 선택",
    );
  });
  it("preserves nested Korean paths and excludes unsupported and sensitive files", () => {
    const result = selectFolder(
      [
        file("회의 자료/운영/정책.md"),
        file("회의 자료/표/예산.XLSX"),
        file("회의 자료/.env"),
        file("회의 자료/.ssh/a.txt"),
        file("회의 자료/node_modules/readme.md"),
        file("회의 자료/photo.png"),
      ],
      limits,
    );
    expect(result.folder).toBe("회의 자료");
    expect(result.accepted.map((f) => f.path)).toEqual([
      "운영/정책.md",
      "표/예산.XLSX",
    ]);
    expect(result.bytes).toBe(20);
    expect(result.picked.filter((f) => f.reason)).toHaveLength(4);
  });
  it("blocks traversal and duplicate normalized names before upload", () => {
    const result = selectFolder(
      [
        file("자료/../escape.txt"),
        file("자료/café.txt"),
        file("자료/cafe\u0301.txt"),
      ],
      limits,
    );
    expect(result.accepted).toHaveLength(1);
  });
  it("counts directories in the ingestion limit and bounds total size", () => {
    expect(
      selectFolder([file("자료/a/b.txt")], { ...limits, max_files: 1 }).error,
    ).toContain("1개");
    expect(
      selectFolder([file("자료/a.txt", 80), file("자료/b.txt", 80)], {
        ...limits,
        max_total_bytes: 100,
      }).error,
    ).toContain("전체");
  });
  it("keeps multiple-file fallback and reports no supported files", () => {
    const plain = {
      name: "readme.txt",
      webkitRelativePath: "",
      size: 10,
    } as File;
    expect(selectFolder([plain], limits).accepted[0].path).toBe("readme.txt");
    expect(selectFolder([file("자료/photo.png")], limits).error).toContain(
      "지원 파일",
    );
    expect(selectFolder([], limits).accepted).toEqual([]);
  });
  it("excludes a file above the per-file ceiling", () => {
    const result = selectFolder(
      [file("자료/large.txt", 101), file("자료/small.md")],
      limits,
    );
    expect(result.accepted.map((f) => f.path)).toEqual(["small.md"]);
    expect(result.picked[0].reason).toContain("크기");
  });
});
