import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  CheckResult,
  Config,
  Prompt,
  PromptList,
  Codex,
  Preview,
} from "./types";
import { errorText } from "./format";

export function useLlmSettings() {
  const [tab, setTab] = useState("connection");
  const [cfg, setCfg] = useState<Config | null>(null),
    [saved, setSaved] = useState<Config | null>(null);
  const [key, setKey] = useState(""),
    [clearKey, setClearKey] = useState(false),
    [models, setModels] = useState<string[]>([]);
  const [codex, setCodex] = useState<Codex | null>(null),
    [authUrl, setAuthUrl] = useState(""),
    [callback, setCallback] = useState("");
  const [check, setCheck] = useState<CheckResult | null>(null),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [listing, setListing] = useState<PromptList | null>(null),
    [editor, setEditor] = useState<Prompt | null>(null),
    [view, setView] = useState<Prompt | null>(null);
  const [sample, setSample] = useState("supported"),
    [preview, setPreview] = useState<Preview | null>(null);
  const dirty =
    JSON.stringify(cfg) !== JSON.stringify(saved) || !!key || clearKey;
  useEffect(() => {
    const controller = new AbortController();
    const get = <T>(path: string) =>
      api<T>(path, undefined, undefined, controller.signal);
    Promise.all([
      get<Config>("/llm/settings"),
      get<{ models: string[] }>("/llm/models"),
      get<PromptList>("/prompts"),
      get<Prompt>("/prompts/active"),
      get<Codex>("/llm/codex/status"),
    ])
      .then(([c, m, l, p, x]) => {
        setCfg(c);
        setSaved(c);
        setCheck(c.last_check);
        setModels(m.models);
        setListing(l);
        setEditor(p);
        setView(p);
        setCodex(x);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!codex?.installed || !authUrl) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      api<Codex>("/llm/codex/status", undefined, undefined, controller.signal)
        .then((x) => {
          setCodex(x);
          if (x.login_status === "error") {
            setAuthUrl("");
            if (!x.connected)
              setError(
                "로그인 세션이 만료됐거나 취소됐습니다. Codex 로그인을 다시 눌러 주세요.",
              );
          }
          if (
            x.login_status === "ok" ||
            (x.connected && x.login_status !== "wait")
          ) {
            setAuthUrl("");
            setNotice(
              "Codex 계정이 연결됐습니다. 모델 목록을 새로 불러오세요.",
            );
          }
        })
        .catch(() => {});
    }, 4000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [codex?.installed, authUrl]);
  async function run(label: string, fn: () => Promise<void>) {
    setBusy(label);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  function accept(c: Config) {
    setCfg(c);
    setSaved(c);
    setKey("");
    setClearKey(false);
    setCheck(c.last_check);
  }
  async function save() {
    if (!cfg) return;
    const {
      base_url,
      default_model,
      enabled,
      max_output_tokens,
      timeout_seconds,
      temperature,
      reasoning_effort,
      input_chars,
    } = cfg;
    accept(
      await api<Config>(
        "/llm/settings",
        {
          expected_version: cfg.version,
          base_url,
          api_key: key,
          clear_api_key: clearKey,
          default_model,
          enabled,
          max_output_tokens,
          timeout_seconds,
          temperature,
          reasoning_effort,
          input_chars,
        },
        "PATCH",
      ),
    );
    setNotice("모델 설정을 저장했습니다. 다음 답변부터 적용됩니다.");
  }
  async function refreshPrompts() {
    setListing(await api<PromptList>("/prompts"));
  }
  async function savePrompt(activate: boolean) {
    if (!editor || !listing) return;
    const r = await api<{ prompt: Prompt; active_id: string }>("/prompts", {
      name: editor.name,
      content: editor.content,
      note: editor.note,
      activate,
      expected_active_id: listing.active_id,
    });
    setEditor(r.prompt);
    setView(r.prompt);
    await refreshPrompts();
    setNotice(
      activate
        ? `프롬프트 v${r.prompt.sequence}를 저장하고 적용했습니다.`
        : `프롬프트 v${r.prompt.sequence}를 저장했습니다. 아직 답변에는 적용되지 않았습니다.`,
    );
  }
  async function applyVersion(restore: boolean) {
    if (!view || !listing) return;
    const r = await api<{ prompt: Prompt }>(
      `/prompts/${view.id}/${restore ? "restore" : "activate"}`,
      { expected_active_id: listing.active_id },
    );
    setEditor(r.prompt);
    setView(r.prompt);
    await refreshPrompts();
    setNotice(`프롬프트 v${r.prompt.sequence}가 활성화됐습니다.`);
  }
  const refreshCodex = () =>
    run("계정 상태 확인 중…", async () => {
      const status = await api<Codex>("/llm/codex/status");
      setCodex(status);
      setNotice(
        status.connected
          ? "Codex 계정이 연결돼 있습니다."
          : "Codex 로그인이 필요합니다.",
      );
    });
  const beginLogin = () =>
    run("로그인 준비 중…", async () => {
      const result = await api<{ url: string }>("/llm/codex/login", {});
      setAuthUrl(result.url);
      setNotice("로그인 후 목록에서 사용할 계정을 선택하세요.");
    });
  const changeAccount = (accountId: string, action: "select" | "delete") =>
    run(
      action === "select" ? "사용 계정 변경 중…" : "계정 삭제 중…",
      async () => {
        if (!codex?.revision) throw new Error("상태 확인 후 다시 시도하세요.");
        try {
          const status = await api<Codex>(`/llm/codex/accounts/${action}`, {
            account_id: accountId,
            expected_revision: codex.revision,
          });
          setCodex(status);
          setCheck(null);
          if (status.error_code)
            throw new Error(
              "변경 후 상태를 확인하지 못했습니다. 상태 확인을 눌러 주세요.",
            );
          setNotice(
            action === "select"
              ? "사용 계정을 변경했습니다. 선택한 계정만 활성화되어 있습니다."
              : "프록시에서 계정을 삭제했습니다. 다시 연결하려면 로그인하세요.",
          );
        } catch (error) {
          // A timed-out request may have changed state; refresh before the next action.
          try {
            setCodex(await api<Codex>("/llm/codex/status"));
          } catch {
            setCodex(null);
          }
          throw error;
        }
      },
    );
  const completeLogin = () =>
    run("로그인 완료 확인 중…", async () => {
      await api("/llm/codex/callback", { redirect_url: callback });
      setCallback("");
      setNotice("인증 결과를 확인하고 있습니다.");
    });
  const useDefaultConnection = () =>
    run("기본 연결 적용 중…", async () => {
      if (!cfg) return;
      accept(
        await api<Config>("/llm/codex/use", { expected_version: cfg.version }),
      );
      setModels([]);
      setNotice("기본 AI 연결 설정을 적용했습니다.");
    });
  const refreshModels = () =>
    run("모델 목록 불러오는 중…", async () => {
      setModels(
        (await api<{ models: string[] }>("/llm/models/refresh", {})).models,
      );
      setNotice(
        "모델 목록을 갱신했습니다. 목록이 비어 있으면 Codex 로그인을 완료하세요.",
      );
    });
  const checkConnection = () =>
    run("선택한 모델의 응답 확인 중…", async () => {
      setCheck(await api<CheckResult>("/llm/check", {}));
    });
  const previewPrompt = () =>
    run("입력 미리보기 준비 중…", async () => {
      if (!editor) return;
      setPreview(
        await api<Preview>("/prompts/preview", {
          content: editor.content,
          case: sample,
        }),
      );
    });
  const testPrompt = () =>
    run("예시 답변 생성 중…", async () => {
      if (!editor) return;
      setPreview(
        await api<Preview>("/prompts/test", {
          content: editor.content,
          case: sample,
        }),
      );
    });
  const selectPrompt = (id: string) =>
    run("버전 불러오는 중…", async () => {
      setView(await api<Prompt>(`/prompts/${id}`));
    });
  function editViewedPrompt() {
    if (!view) return;
    setEditor({ ...view, note: "" });
    setPreview(null);
    setNotice(
      `v${view.sequence}를 편집기로 불러왔습니다. 수정 후 새 버전으로 저장하세요.`,
    );
  }
  return {
    tab,
    setTab,
    cfg,
    saved,
    key,
    clearKey,
    models,
    codex,
    authUrl,
    callback,
    check,
    busy,
    error,
    notice,
    listing,
    editor,
    view,
    sample,
    preview,
    dirty,
    setCfg,
    setKey,
    setClearKey,
    setModels,
    setCodex,
    setAuthUrl,
    setCallback,
    setCheck,
    setError,
    setNotice,
    setEditor,
    setView,
    setSample,
    setPreview,
    run,
    accept,
    save,
    savePrompt,
    applyVersion,
    refreshCodex,
    beginLogin,
    changeAccount,
    completeLogin,
    useDefaultConnection,
    refreshModels,
    checkConnection,
    previewPrompt,
    testPrompt,
    selectPrompt,
    editViewedPrompt,
  };
}
export type LlmSettingsController = ReturnType<typeof useLlmSettings>;
export type ReadyLlmSettings = LlmSettingsController & {
  cfg: Config;
  editor: Prompt;
  listing: PromptList;
};
