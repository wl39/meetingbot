import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, setCsrf, uploadFile, type Workspace } from "../rag/api";
import { getTutorialExamples, prepareTutorialExample } from "./samples";

vi.mock("../rag/api", () => ({
  api: vi.fn(),
  setCsrf: vi.fn(),
  uploadFile: vi.fn(),
}));

const ready: Workspace = {
  id: "recipes-workspace",
  name: "한국 인기 요리 레시피",
  description: "체험용 요리 문서",
  state: "READY",
  document_count: 1,
  active_revision_id: "revision-1",
  consent: null,
  source: {
    root_id: "uploads",
    relative_path: "tutorial",
    kind: "upload",
  },
  latest_job: null,
};

const sample = readFileSync(
  new URL("../../../public/assets/tutorial/korean-recipes.md", import.meta.url),
  "utf8",
);

function mockRecipeUpload(commit: Workspace = ready) {
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/workspaces") return [];
    if (path === "/auth/session") return { csrf: "tutorial-csrf" };
    if (path === "/uploads")
      return {
        id: "upload-1",
        files: [{ id: "file-1", path: "korean-recipes.md", received: false }],
      };
    if (path === "/uploads/upload-1/commit")
      return { workspace: commit, job: commit.latest_job, index_error: null };
    if (path === "/workspaces/recipes-workspace") return ready;
    return {};
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(uploadFile).mockResolvedValue(undefined);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, text: async () => sample }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("tutorial examples", () => {
  it("recognizes decomposed Korean folder names from macOS", () => {
    const recipes = {
      ...ready,
      name: "한국_인기요리_레시피_125".normalize("NFD"),
    };
    const news = { ...ready, id: "news", name: "모닝브루".normalize("NFD") };
    const examples = getTutorialExamples([recipes, news]);
    expect(examples[0].workspace?.id).toBe(recipes.id);
    expect(examples[1]).toMatchObject({ available: true, workspace: news });
    expect(
      getTutorialExamples([{ ...ready, name: "한국 시장 분석" }])[0].workspace,
    ).toBeNull();
  });
  it("offers authored recipes and only offers Morning Brew when real documents exist", () => {
    const missing = getTutorialExamples([]);
    expect(missing[0].available).toBe(true);
    expect(missing[1]).toMatchObject({ available: false, workspace: null });
    const connected = { ...ready, id: "news", name: "Morning Brew" };
    expect(getTutorialExamples([connected])[1]).toMatchObject({
      available: true,
      workspace: connected,
    });
    expect(
      getTutorialExamples([{ ...connected, document_count: 0 }])[1].available,
    ).toBe(false);
  });

  it("reuses a searchable recipe workspace without uploading duplicates", async () => {
    const existing = { ...ready, name: "한식 모음" };
    await expect(
      prepareTutorialExample(
        "recipes",
        [existing],
        new AbortController().signal,
      ),
    ).resolves.toBe(existing);
    expect(api).not.toHaveBeenCalled();
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("refreshes a stale workspace list before creating an example", async () => {
    vi.mocked(api).mockResolvedValue([ready]);
    await expect(
      prepareTutorialExample("recipes", [], new AbortController().signal),
    ).resolves.toBe(ready);
    expect(api).toHaveBeenCalledTimes(1);
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("uploads the bundled Korean recipe text and waits for a searchable workspace", async () => {
    vi.useFakeTimers();
    const building: Workspace = {
      ...ready,
      state: "REGISTERED",
      document_count: 0,
      active_revision_id: null,
      latest_job: {
        job_id: "job-1",
        state: "RUNNING",
        revision_id: null,
        workspace_id: ready.id,
        cancel: 0,
        result: {},
      },
    };
    mockRecipeUpload(building);
    const signal = new AbortController().signal;
    const preparing = prepareTutorialExample("recipes", [], signal);
    await vi.advanceTimersByTimeAsync(750);
    await expect(preparing).resolves.toEqual(ready);
    expect(setCsrf).toHaveBeenCalledWith("tutorial-csrf");
    const [path, file, uploadSignal] = vi.mocked(uploadFile).mock.calls[0];
    expect(path).toBe("/uploads/upload-1/files/file-1");
    expect(uploadSignal).toBe(signal);
    expect(file.name).toBe("korean-recipes.md");
    const text = await file.text();
    for (const recipe of ["김치볶음밥", "비빔밥", "떡볶이"])
      expect(text).toContain(`## ${recipe}`);
    expect(text).toContain("직접 작성한 예제");
    expect(api).toHaveBeenCalledWith("/uploads/upload-1/commit", {});
    expect(api).toHaveBeenCalledWith(
      "/workspaces/recipes-workspace",
      undefined,
      undefined,
      signal,
    );
  });

  it("removes an uncommitted upload when cancellation arrives during session creation", async () => {
    const controller = new AbortController();
    vi.mocked(api).mockImplementation(async (path) => {
      if (path === "/workspaces") return [];
      if (path === "/auth/session") return { csrf: "csrf" };
      if (path === "/uploads") {
        controller.abort();
        return { id: "cancelled-upload", files: [] };
      }
      return {};
    });
    await expect(
      prepareTutorialExample("recipes", [], controller.signal),
    ).rejects.toMatchObject({ name: "AbortError" });
    expect(api).toHaveBeenCalledWith(
      "/uploads/cancelled-upload",
      undefined,
      "DELETE",
    );
    expect(uploadFile).not.toHaveBeenCalled();
  });

  it("retries a lost commit response using the same upload session", async () => {
    mockRecipeUpload();
    const implementation = vi.mocked(api).getMockImplementation()!;
    let commits = 0;
    vi.mocked(api).mockImplementation(async (...args) => {
      if (args[0] === "/uploads/upload-1/commit" && ++commits === 1)
        throw new Error("connection lost");
      return implementation(...args);
    });
    await expect(
      prepareTutorialExample("recipes", [], new AbortController().signal),
    ).resolves.toEqual(ready);
    expect(commits).toBe(2);
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(
      vi.mocked(api).mock.calls.filter(([path]) => path === "/uploads"),
    ).toHaveLength(1);
  });

  it("shares a simultaneous recipe preparation instead of creating another upload", async () => {
    mockRecipeUpload();
    const signal = new AbortController().signal;
    const first = prepareTutorialExample("recipes", [], signal);
    const second = prepareTutorialExample("recipes", [], signal);
    await expect(Promise.all([first, second])).resolves.toEqual([ready, ready]);
    expect(uploadFile).toHaveBeenCalledTimes(1);
    expect(
      vi.mocked(api).mock.calls.filter(([path]) => path === "/uploads"),
    ).toHaveLength(1);
  });

  it("does not fabricate or upload Morning Brew content", async () => {
    await expect(
      prepareTutorialExample("morningbrew", [], new AbortController().signal),
    ).rejects.toThrow("연결된 모닝브루 문서가 없습니다");
    expect(api).not.toHaveBeenCalled();
    expect(uploadFile).not.toHaveBeenCalled();
  });
});
