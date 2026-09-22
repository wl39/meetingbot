import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  Check,
  CircleHelp,
  FileAudio,
  FolderOpen,
  LoaderCircle,
  Mic,
  Search,
  Upload,
  X,
} from "lucide-react";
import { api, setCsrf, type Workspace } from "../rag/api";
import { useWorkspace } from "../../workspace/context";
import { useOnboarding } from "./context";
import { getTutorialExamples, prepareTutorialExample } from "./samples";
import "./onboarding.css";

export function TutorialButton() {
  const tutorial = useOnboarding();
  const { busyMode } = useWorkspace();
  return (
    <button
      className="workspace-tutorial"
      aria-label="사용 가이드"
      title="사용 가이드"
      disabled={!!busyMode}
      onClick={() => tutorial?.restart()}
    >
      <CircleHelp size={17} aria-hidden="true" />
      <span>사용 가이드</span>
    </button>
  );
}

export default function OnboardingGuide() {
  const tutorial = useOnboarding()!;
  const { state } = tutorial;
  const { access, view, busyMode, navigate } = useWorkspace();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [preparing, setPreparing] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const dismiss = useRef(tutorial.dismiss);
  dismiss.current = tutorial.dismiss;
  const welcome =
    access.authenticated &&
    state.step === "welcome" &&
    view !== "settings" &&
    !busyMode;
  useEffect(() => {
    if (!welcome) return;
    const element = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    element?.showModal();
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      element?.close();
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [welcome]);
  useEffect(() => {
    if (state.step !== "documents") return;
    const abort = new AbortController();
    setLoading(true);
    setError("");
    void api<{ csrf: string }>(
      "/auth/session",
      undefined,
      undefined,
      abort.signal,
    )
      .then((session) => {
        setCsrf(session.csrf);
        return api<Workspace[]>(
          "/workspaces",
          undefined,
          undefined,
          abort.signal,
        );
      })
      .then(setWorkspaces)
      .catch(() => {
        if (!abort.signal.aborted)
          setError("문서를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.");
      })
      .finally(() => {
        if (!abort.signal.aborted) setLoading(false);
      });
    return () => abort.abort();
  }, [state.step, retry]);
  useEffect(() => {
    if (state.step !== "documents") {
      controller.current?.abort();
      setPreparing(null);
    }
    return () => controller.current?.abort();
  }, [state.step]);
  async function prepare(id: "recipes" | "morningbrew") {
    if (preparing) return;
    const abort = new AbortController();
    controller.current = abort;
    setPreparing(id);
    setError("");
    try {
      const example = getTutorialExamples(workspaces).find(
        (item) => item.id === id,
      )!;
      const workspace = await prepareTutorialExample(
        id,
        workspaces,
        abort.signal,
      );
      if (!abort.signal.aborted)
        tutorial.selectWorkspace(workspace, example.query, example.voicePrompt);
    } catch (caught) {
      if (!abort.signal.aborted)
        setError(
          caught instanceof Error
            ? caught.message
            : "예제 문서를 열지 못했습니다. 다시 시도해 주세요.",
        );
    } finally {
      if (!abort.signal.aborted) setPreparing(null);
    }
  }
  if (!access.authenticated) return null;
  if (welcome)
    return (
      <dialog
        ref={dialog}
        className="tutorial-welcome"
        aria-labelledby="tutorial-title"
        onCancel={(event) => {
          event.preventDefault();
          dismiss.current();
        }}
      >
        <button
          className="tutorial-close"
          aria-label="가이드 닫기"
          onClick={tutorial.dismiss}
        >
          <X size={20} />
        </button>
        <div className="tutorial-welcome-icon">
          <BookOpen size={27} />
        </div>
        <p className="tutorial-eyebrow">처음이라면, 함께 시작해요</p>
        <h1 id="tutorial-title">
          회의에 사용할 문서들이
          <br />
          준비되었나요?
        </h1>
        <p className="tutorial-intro">
          문서에서 답을 찾고, 음성과 파일로 직접 체험해 보세요.
          <br />
          준비된 자료가 없어도 괜찮아요.
        </p>
        <div className="tutorial-choices">
          <button onClick={() => tutorial.begin("own")}>
            <FolderOpen size={23} />
            <span>
              <strong>네, 준비되어 있어요</strong>
              <small>내 문서를 올리거나 기존 워크스페이스로 시작</small>
            </span>
            <ArrowRight size={19} />
          </button>
          <button onClick={() => tutorial.begin("sample")}>
            <BookOpen size={23} />
            <span>
              <strong>아니요, 먼저 체험할게요</strong>
              <small>한국 인기 요리 레시피나 모닝브루로 시작</small>
            </span>
            <ArrowRight size={19} />
          </button>
        </div>
        <div className="tutorial-preview">
          <span>문서 준비</span>
          <ArrowRight />
          <span>검색</span>
          <ArrowRight />
          <span>음성</span>
          <ArrowRight />
          <span>파일</span>
        </div>
        <button className="tutorial-text-button" onClick={tutorial.dismiss}>
          나중에 둘러볼게요
        </button>
      </dialog>
    );
  if (["welcome", "dismissed"].includes(state.step) || view === "settings")
    return null;
  if (state.step === "done")
    return (
      <section
        className="tutorial-guide tutorial-finish"
        aria-label="가이드 마침"
      >
        <span className="tutorial-complete-icon">
          <Check size={24} />
        </span>
        <div>
          <h2>이제 내 회의에 활용해 보세요</h2>
          <p>
            문서를 선택하고, 녹음하거나 파일을 올리면 됩니다. 사용 가이드는
            언제든 다시 열 수 있어요.
          </p>
        </div>
        <button
          className="primary"
          onClick={() => {
            tutorial.dismiss();
            navigate("/rag");
          }}
        >
          시작하기 <ArrowRight size={16} />
        </button>
      </section>
    );
  const steps = [
    { id: "documents", label: "문서 준비", Icon: FolderOpen },
    { id: "search", label: "직접 검색", Icon: Search },
    { id: "voice", label: "음성 테스트", Icon: Mic },
    { id: "file", label: "파일 업로드", Icon: FileAudio },
  ] as const;
  const current = steps.findIndex((step) => step.id === state.step);
  return (
    <section className="tutorial-guide" aria-label="시작 가이드">
      <div className="tutorial-guide-top">
        <ol className="tutorial-steps" aria-label="체험 순서">
          {steps.map((step, index) => (
            <li
              key={step.id}
              className={
                index === current ? "current" : index < current ? "past" : ""
              }
              aria-current={index === current ? "step" : undefined}
            >
              <span>{index + 1}</span>
              {step.label}
            </li>
          ))}
        </ol>
        <button
          className="tutorial-close-inline"
          onClick={tutorial.dismiss}
          aria-label="가이드 닫기"
        >
          <X size={18} />
        </button>
      </div>
      <div className="tutorial-guide-body">
        {state.step === "documents" && (
          <>
            <div className="tutorial-copy">
              <p className="tutorial-eyebrow">01 · 문서 준비</p>
              <h2>
                {state.source === "own"
                  ? "어떤 문서로 시작할까요?"
                  : "가볍게 체험할 자료를 골라보세요"}
              </h2>
              <p>
                {state.source === "own"
                  ? "기존 워크스페이스를 선택하거나, 회의에 사용할 문서를 올려 주세요."
                  : "예제 문서를 직접 검색하고, 같은 내용으로 음성도 테스트할 수 있어요."}
              </p>
              <button
                className="tutorial-text-button"
                disabled={!!preparing}
                onClick={() =>
                  tutorial.setSource(state.source === "own" ? "sample" : "own")
                }
              >
                {state.source === "own"
                  ? "문서 없이 예제로 체험할게요"
                  : "내 문서로 시작할게요"}
              </button>
            </div>
            <div className="tutorial-document-options">
              {loading ? (
                <p role="status">
                  <LoaderCircle className="spin" size={17} /> 문서를 불러오는
                  중…
                </p>
              ) : state.source === "sample" ? (
                getTutorialExamples(workspaces).map((example) => (
                  <button
                    key={example.id}
                    className="tutorial-document"
                    disabled={!!preparing || !example.available}
                    onClick={() => void prepare(example.id)}
                  >
                    <BookOpen size={20} />
                    <span>
                      <strong>{example.name}</strong>
                      <small>{example.description}</small>
                    </span>
                    {preparing === example.id ? (
                      <LoaderCircle className="spin" size={18} />
                    ) : (
                      <ArrowRight size={17} />
                    )}
                  </button>
                ))
              ) : (
                <>
                  <button
                    className="tutorial-document"
                    onClick={tutorial.openCreate}
                  >
                    <Upload size={21} />
                    <span>
                      <strong>내 문서 올리기</strong>
                      <small>
                        파일이나 폴더를 선택해 워크스페이스를 만드세요
                      </small>
                    </span>
                    <ArrowRight size={17} />
                  </button>
                  {workspaces.length > 0 && (
                    <label className="tutorial-existing">
                      기존 워크스페이스로 시작
                      <select
                        aria-label="체험할 워크스페이스"
                        value=""
                        onChange={(event) => {
                          const ws = workspaces.find(
                            (w) => w.id === event.target.value,
                          );
                          if (ws) tutorial.selectWorkspace(ws);
                        }}
                      >
                        <option value="" disabled>
                          워크스페이스 선택
                        </option>
                        {workspaces.map((ws) => (
                          <option key={ws.id} value={ws.id}>
                            {ws.name} · 문서 {ws.document_count}개
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </>
              )}
              {preparing && (
                <p className="tutorial-note" role="status">
                  예제 문서를 여는 중이에요. 처음에는 잠시 걸릴 수 있습니다.
                </p>
              )}
              {error && (
                <div className="tutorial-error" role="alert">
                  <p>{error}</p>
                  <button
                    onClick={() => {
                      setRetry((value) => value + 1);
                    }}
                  >
                    다시 불러오기
                  </button>
                </div>
              )}
            </div>
          </>
        )}
        {state.step === "search" && (
          <>
            <div className="tutorial-copy">
              <p className="tutorial-eyebrow">02 · 직접 검색</p>
              <h2>문서에 궁금한 점을 물어보세요</h2>
              <p>
                <strong>{state.workspaceName}</strong>에서 검색해 보세요. 아래
                검색창에 질문을 입력하고 ‘문서 검색’을 누르면 출처까지 확인할 수
                있어요.
              </p>
              <button className="tutorial-prompt" onClick={tutorial.fillQuery}>
                <Search size={16} />
                <span>{state.query}</span>
                <span>질문 넣기</span>
              </button>
            </div>
            <div className="tutorial-next">
              {state.searched ? (
                <p className="tutorial-success">
                  <Check size={17} />
                  검색 결과를 확인했어요
                </p>
              ) : (
                <p>먼저 아래에서 검색을 한 번 해보세요.</p>
              )}
              {view !== "rag" && (
                <button onClick={tutorial.openWorkspace}>검색 화면 열기</button>
              )}
              <button
                className="primary"
                disabled={!state.searched || !!busyMode}
                onClick={() => tutorial.go("voice")}
              >
                음성으로 이어서 <ArrowRight size={17} />
              </button>
              <button
                className="tutorial-text-button"
                disabled={!!busyMode}
                onClick={() => tutorial.go("documents")}
              >
                문서 다시 선택
              </button>
            </div>
          </>
        )}
        {state.step === "voice" && (
          <>
            <div className="tutorial-copy">
              <p className="tutorial-eyebrow">03 · 음성 테스트</p>
              <h2>이번에는 직접 말해보세요</h2>
              <p>
                녹음 파일이 없어도 괜찮아요. ‘녹음 시작’을 누르고 짧게 말한 뒤
                멈춰 보세요. 마이크 사용을 허용하면 내 말이 대본으로 나타납니다.
              </p>
              <blockquote className="tutorial-spoken">
                “{state.voicePrompt}”
              </blockquote>
              <p className="tutorial-note">
                ‘문서 참고 켜기’를 누르면 {state.workspaceName}의 문서로 대화
                내용을 함께 확인할 수 있어요.
              </p>
            </div>
            <div className="tutorial-next">
              {state.recorded && (
                <p className="tutorial-success">
                  <Check size={17} />
                  음성 기록을 만들었어요
                </p>
              )}
              {view !== "live" && (
                <button disabled={!!busyMode} onClick={() => navigate("/live")}>
                  음성 화면 열기
                </button>
              )}
              <button
                className="primary"
                disabled={!state.recorded || !!busyMode}
                onClick={() => tutorial.go("file")}
              >
                파일로 이어서 <ArrowRight size={17} />
              </button>
              <button
                className="tutorial-text-button"
                disabled={!!busyMode}
                onClick={() => tutorial.go("file")}
              >
                마이크 사용이 어려워요 · 건너뛰기
              </button>
            </div>
          </>
        )}
        {state.step === "file" && (
          <>
            <div className="tutorial-copy">
              <p className="tutorial-eyebrow">04 · 파일 업로드</p>
              <h2>
                {tutorial.audioFile
                  ? "방금 녹음한 음성을 파일로 올려보세요"
                  : "녹음 파일도 같은 방법으로 확인하세요"}
              </h2>
              <p>
                {tutorial.audioFile
                  ? "아래 ‘방금 녹음한 음성 사용’을 누르고 업로드를 시작하세요. 직접 가진 회의 파일을 선택해도 좋아요."
                  : "아래에서 회의 음성 파일을 선택하고 업로드를 시작해 보세요. 파일이 없다면 음성 단계에서 짧게 녹음하거나, 다음에 해도 괜찮아요."}
              </p>
              <p className="tutorial-note">
                WAV, MP3, M4A, FLAC 파일을 사용할 수 있어요.
              </p>
            </div>
            <div className="tutorial-next">
              {state.uploaded && (
                <p className="tutorial-success">
                  <Check size={17} />
                  파일로 대본을 만들었어요
                </p>
              )}
              {view !== "file" && (
                <button disabled={!!busyMode} onClick={() => navigate("/")}>
                  파일 화면 열기
                </button>
              )}
              <button
                className="primary"
                disabled={!state.uploaded || !!busyMode}
                onClick={() => tutorial.go("done")}
              >
                체험 마치기 <Check size={17} />
              </button>
              {!tutorial.audioFile && (
                <button
                  className="tutorial-text-button"
                  disabled={!!busyMode}
                  onClick={() => tutorial.go("voice")}
                >
                  파일 대신 짧게 녹음하기
                </button>
              )}
              <button
                className="tutorial-text-button"
                disabled={!!busyMode}
                onClick={() => tutorial.go("done")}
              >
                파일 업로드는 다음에 할게요
              </button>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
