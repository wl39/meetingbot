import { api, setCsrf, uploadFile, type Job, type Workspace } from "../rag/api";

export type TutorialExampleId = "recipes" | "morningbrew";
export type TutorialExample = {
  id: TutorialExampleId;
  name: string;
  description: string;
  query: string;
  voicePrompt: string;
  workspace: Workspace | null;
  available: boolean;
};

const recipeName = "한국 인기 요리 레시피";
const recipeDescription =
  "김치볶음밥, 비빔밥, 떡볶이의 재료와 만드는 순서를 담은 체험용 문서입니다.";
const pendingJobs = new Set([
  "QUEUED",
  "RUNNING",
  "SCANNING",
  "BUILDING",
  "VALIDATING",
]);

function accessible(workspace: Workspace) {
  return !workspace.access_state || workspace.access_state === "AVAILABLE";
}

function searchable(workspace: Workspace) {
  return (
    accessible(workspace) &&
    !!workspace.active_revision_id &&
    workspace.document_count > 0
  );
}

function findExample(id: TutorialExampleId, workspaces: Workspace[]) {
  const pattern =
    id === "recipes"
      ? /한국.*요리|한식|레시피|recipes?/i
      : /morning[\s_-]*brew|모닝\s*브루/i;
  const matches = workspaces.filter(
    (workspace) =>
      accessible(workspace) &&
      pattern.test(
        `${workspace.name} ${workspace.source?.label || ""}`.normalize("NFC"),
      ),
  );
  return (
    matches.find(searchable) ||
    matches.find(
      (workspace) => workspace.source && workspace.can_manage !== false,
    ) ||
    null
  );
}

export function getTutorialExamples(
  workspaces: Workspace[],
): TutorialExample[] {
  const recipes = findExample("recipes", workspaces);
  const morningbrew = findExample("morningbrew", workspaces);
  const morningbrewReady = !!morningbrew && searchable(morningbrew);
  return [
    {
      id: "recipes",
      name: recipeName,
      description: recipes
        ? "한국 인기 요리의 재료와 만드는 방법을 검색해 보세요."
        : recipeDescription,
      query: "김치볶음밥에 필요한 재료와 만드는 순서를 알려주세요.",
      voicePrompt:
        "점심 메뉴로 김치볶음밥을 만들려고 해요. 필요한 재료와 만드는 순서를 확인해 주세요.",
      workspace: recipes,
      available: true,
    },
    {
      id: "morningbrew",
      name: "모닝브루",
      description: morningbrewReady
        ? "연결된 모닝브루 문서를 검색하고 주요 내용을 확인해 보세요."
        : "연결된 모닝브루 문서가 아직 없습니다. 한식 레시피로 먼저 시작해 보세요.",
      query: "문서에서 소개하는 주요 소식과 핵심 내용을 알려주세요.",
      voicePrompt:
        "오늘 함께 살펴볼 문서에서 주요 소식과 핵심 내용을 찾아 주세요.",
      workspace: morningbrewReady ? morningbrew : null,
      available: morningbrewReady,
    },
  ];
}

function pause(signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    signal.throwIfAborted();
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason || new DOMException("취소했습니다.", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, 750);
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function waitUntilSearchable(workspace: Workspace, signal: AbortSignal) {
  const startedAt = Date.now();
  let current = workspace;
  while (true) {
    signal.throwIfAborted();
    if (searchable(current)) return current;
    if (current.latest_job && !pendingJobs.has(current.latest_job.state)) {
      throw new Error(
        "예제 문서를 준비하지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
    }
    if (Date.now() - startedAt > 180_000) {
      throw new Error(
        "문서를 준비하는 데 시간이 걸리고 있습니다. 잠시 후 예제를 다시 선택해 주세요.",
      );
    }
    await pause(signal);
    current = await api<Workspace>(
      `/workspaces/${encodeURIComponent(workspace.id)}`,
      undefined,
      undefined,
      signal,
    );
  }
}

type UploadSession = {
  id: string;
  files: { id: string; path: string; received: boolean }[];
};
type UploadResult = {
  workspace: Workspace;
  job: Job | null;
  index_error: string | null;
};

async function prepareRecipes(signal: AbortSignal) {
  signal.throwIfAborted();
  // Refresh before creating: the caller's list may predate an earlier attempt.
  const latest = await api<Workspace[]>(
    "/workspaces",
    undefined,
    undefined,
    signal,
  );
  const existing = findExample("recipes", latest);
  if (existing && searchable(existing)) return existing;

  const session = await api<{ csrf: string }>(
    "/auth/session",
    undefined,
    undefined,
    signal,
  );
  setCsrf(session.csrf);
  if (existing) {
    let current = existing;
    if (!pendingJobs.has(current.latest_job?.state || "")) {
      const job = await api<Job>(
        `/workspaces/${encodeURIComponent(current.id)}/index-jobs`,
        {},
        undefined,
        signal,
      );
      current = { ...current, latest_job: job };
    }
    return waitUntilSearchable(current, signal);
  }

  // Only authored tutorial material is bundled; no news content is invented.
  const response = await fetch("/assets/tutorial/korean-recipes.md", {
    signal,
  });
  if (!response.ok) throw new Error("예제 문서를 불러오지 못했습니다.");
  const text = await response.text();
  signal.throwIfAborted();
  const file = new File([text], "korean-recipes.md", { type: "text/markdown" });
  let upload: UploadSession | null = null;
  let committed = false;
  try {
    // Keep the creation response available even if the user cancels, so its
    // upload session can be removed instead of becoming an orphan.
    upload = await api<UploadSession>("/uploads", {
      name: recipeName,
      description: recipeDescription,
      folder_name: "한국 인기 요리 레시피",
      files: [{ path: file.name, size: file.size }],
    });
    signal.throwIfAborted();
    const target = upload.files.find((entry) => entry.path === file.name);
    if (!target) throw new Error("예제 문서의 업로드를 준비하지 못했습니다.");
    if (!target.received) {
      await uploadFile(
        `/uploads/${upload.id}/files/${target.id}`,
        file,
        signal,
        () => {},
      );
    }
    signal.throwIfAborted();
    const commitPath = `/uploads/${upload.id}/commit`;
    let result: UploadResult;
    try {
      result = await api<UploadResult>(commitPath, {});
    } catch {
      signal.throwIfAborted();
      // Retrying the same idempotent commit handles a lost response without
      // uploading again or creating a second workspace.
      result = await api<UploadResult>(commitPath, {});
    }
    committed = true;
    signal.throwIfAborted();
    if (result.index_error) {
      throw new Error(
        "예제 문서는 저장되었습니다. 잠시 후 다시 선택하면 이어서 준비합니다.",
      );
    }
    return await waitUntilSearchable(
      {
        ...result.workspace,
        latest_job: result.job || result.workspace.latest_job,
      },
      signal,
    );
  } finally {
    if (upload && !committed) {
      await api(`/uploads/${upload.id}`, undefined, "DELETE").catch(() => {});
    }
  }
}

const recipesInProgress = new WeakMap<AbortSignal, Promise<Workspace>>();

export async function prepareTutorialExample(
  id: TutorialExampleId,
  workspaces: Workspace[],
  signal: AbortSignal,
): Promise<Workspace> {
  signal.throwIfAborted();
  const example = getTutorialExamples(workspaces).find(
    (item) => item.id === id,
  );
  if (example?.workspace && searchable(example.workspace))
    return example.workspace;
  if (id === "morningbrew") {
    throw new Error(
      "연결된 모닝브루 문서가 없습니다. 한식 레시피를 선택해 주세요.",
    );
  }
  let pending = recipesInProgress.get(signal);
  if (!pending) {
    pending = prepareRecipes(signal).finally(() =>
      recipesInProgress.delete(signal),
    );
    recipesInProgress.set(signal, pending);
  }
  const workspace = await pending;
  signal.throwIfAborted();
  return workspace;
}
