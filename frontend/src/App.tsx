import { useCallback, useEffect, useRef, useState } from "react";
import { Clock3, X, KeyRound, ChevronRight, Trash2 } from "lucide-react";
import {
  api,
  latestSnapshot,
  warningMessage,
  errorMessage,
  type Health,
  type Session,
} from "./features/stt/api";
import {
  DeleteRecordDialog,
  RecordsDialog,
  RecordsList,
  recordName,
  type RecordSummary,
} from "./features/stt/Records";
import { FileTranscriptionPage } from "./features/stt/FileTranscriptionPage";
import { LiveTranscriptionPage } from "./features/stt/LiveTranscriptionPage";
import { TranscriptView } from "./features/stt/TranscriptView";
import { LocalAudioPlayer } from "./features/stt/LocalAudioPlayer";
import { MeetingAssistant } from "./features/meeting/MeetingAssistant";
import type { AudioSeek } from "./features/stt/waveform";
import type { PlaybackRange } from "./features/stt/script";
import { useWorkspace } from "./workspace/context";
import { useOnboarding } from "./features/onboarding/context";
export default function App() {
  const { view, sttMode, navigate, setBusyMode, credential, connect, access } =
    useWorkspace();
  const authenticated = access.authenticated;
  const tutorial = useOnboarding();
  const tutorialSessions = useRef(new Set<string>());
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localFiles, setLocalFiles] = useState<Record<string, File>>({});
  const [seek, setSeek] = useState<AudioSeek | null>(null);
  const [playbackMs, setPlaybackMs] = useState(0);
  const [syncEnabled, setSyncEnabled] = useState(false);
  const [highlightWords, setHighlightWords] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
  const [recordsOpen, setRecordsOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const deletedIds = useRef(new Set<string>());
  const seekToUtterance = useCallback(
    (u: PlaybackRange) =>
      setSeek({
        ms: u.start_ms,
        endMs: u.end_ms,
        utteranceId: u.utterance_id,
        key: performance.now(),
      }),
    [],
  );
  const [key, setKey] = useState(""),
    [mode, setMode] = useState<"file" | "live">(sttMode),
    [health, setHealth] = useState<Health | null>(null),
    [session, setSession] = useState<Session | null>(null),
    [history, setHistory] = useState<RecordSummary[]>([]),
    [error, setError] = useState(""),
    [recording, setRecording] = useState(false);
  useEffect(() => {
    if ((view === "file" || view === "live") && mode !== sttMode) {
      setMode(sttMode);
      setSession(null);
      window.scrollTo(0, 0);
    }
  }, [view, sttMode, mode]);
  useEffect(() => {
    setBusyMode(recording ? mode : null);
    return () => setBusyMode(null);
  }, [recording, mode, setBusyMode]);
  const receiveSession = useCallback(
    (incoming: Session) => {
      if (deletedIds.current.has(incoming.id)) return;
      if (tutorial?.active) tutorialSessions.current.add(incoming.id);
      setSession((current) => latestSnapshot(current, incoming));
    },
    [tutorial?.active],
  );
  useEffect(() => {
    if (
      !tutorial?.active ||
      !session ||
      !tutorialSessions.current.has(session.id) ||
      !["COMPLETED", "PARTIAL"].includes(session.state) ||
      !session.utterances.some(
        (utterance) =>
          !["partial", "retracted"].includes(utterance.status) &&
          !!utterance.text.trim(),
      )
    )
      return;
    if (session.mode === "file") tutorial.reportFile();
    else tutorial.reportVoice();
    tutorialSessions.current.delete(session.id);
  }, [session, tutorial?.active, tutorial?.reportFile, tutorial?.reportVoice]);
  const refresh = useCallback(() => {
    if (session)
      api<Session>(`/sessions/${session.id}`)
        .then((incoming) =>
          setSession((current) =>
            current?.id === incoming.id
              ? latestSnapshot(current, incoming)
              : current,
          ),
        )
        .catch((e) => {
          if (String(e).includes("NOT_FOUND")) setSession(null);
          else setError(String(e));
        });
  }, [session?.id]);
  useEffect(() => {
    if (!authenticated) return;
    let alive = true;
    let pending = false;
    async function tick() {
      if (pending) return;
      pending = true;
      try {
        const [h, list] = await Promise.all([
          api<Health>("/health"),
          api<typeof history>("/sessions"),
        ]);
        if (alive) {
          setHealth(h);
          setHistory(list.filter((item) => !deletedIds.current.has(item.id)));
        }
      } catch (e) {
        if (alive) {
          setError(String(e));
          setHealth(null);
          if (String(e).includes("LOCAL_AUTH_REQUIRED")) {
            connect("");
          }
        }
      } finally {
        pending = false;
      }
    }
    void tick();
    const timer = setInterval(tick, 2500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [authenticated, credential, connect]);
  useEffect(() => {
    if (!session) return;
    const timer = setInterval(refresh, 1000);
    return () => clearInterval(timer);
  }, [session?.id, refresh]);
  async function choose(id: string) {
    try {
      const incoming = await api<Session>(`/sessions/${id}`);
      if (deletedIds.current.has(id)) return;
      const nextMode = incoming.mode === "microphone" ? "live" : "file";
      setMode(nextMode);
      navigate(nextMode === "live" ? "/live" : "/");
      setSession(incoming);
      setRecordsOpen(false);
    } catch (e) {
      setError(String(e));
    }
  }
  function requestDelete(id: string, name: string) {
    if (recording || deleting) return;
    setDeleteError("");
    setDeleteTarget({ id, name });
  }
  async function deleteRecord() {
    if (!deleteTarget || deleting || recording) return;
    const id = deleteTarget.id;
    setDeleting(true);
    setDeleteError("");
    try {
      await api(`/sessions/${id}`, { method: "DELETE" });
      deletedIds.current.add(id);
      tutorialSessions.current.delete(id);
      if (tutorial?.audioSessionId === id) {
        setSelectedFile((file) => (file === tutorial.audioFile ? null : file));
      }
      tutorial?.forgetVoice(id);
      setHistory((items) => items.filter((item) => item.id !== id));
      setLocalFiles((files) => {
        const next = { ...files };
        delete next[id];
        return next;
      });
      if (session?.id === id) {
        setSession(null);
        setSelectedFile(null);
        setSeek(null);
        setPlaybackMs(0);
        setSyncEnabled(false);
        setHighlightWords(false);
      }
      setDeleteTarget(null);
    } catch (e) {
      setDeleteError(errorMessage(String(e)));
    } finally {
      setDeleting(false);
    }
  }
  const recordsList = (
    <RecordsList
      records={history}
      selectedId={session?.id}
      query={historyQuery}
      onQuery={setHistoryQuery}
      busy={recording || deleting}
      onSelect={(id) => void choose(id)}
      onDelete={(record) => requestDelete(record.id, recordName(record))}
    />
  );
  const currentRecordName =
    session?.source_file?.name ||
    (mode === "live" ? "마이크 녹음" : "파일 전사");
  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="내 기록">
        <h2 className="record-sidebar-heading">
          <Clock3 size={17} /> 내 기록
        </h2>
        {recordsList}
      </aside>
      <main>
        <header className="topbar">
          <span>
            워크스페이스 <ChevronRight size={13} />
            {mode === "file" ? "파일 전사" : "실시간 전사"}
          </span>
        </header>
        <div className="content">
          <div className="page-title record-page-title">
            <div>
              <h1>
                {session?.source_file?.name
                  ? session.source_file.name.replace(/\.[^.]+$/, "")
                  : mode === "file"
                    ? "파일 전사"
                    : "실시간 전사"}
              </h1>
              <p>
                {session?.utterances.length
                  ? "대본을 다듬고, 화자를 정리하고, 필요한 구간을 다시 들어보세요."
                  : mode === "file"
                    ? "녹음 파일을 읽기 쉬운 회의 기록으로 정리하세요."
                    : "대화를 기록하고, 관련 자료를 함께 확인하세요."}
              </p>
            </div>
            {authenticated && (
              <div className="record-page-actions">
                <button
                  className="record-mobile-toggle"
                  onClick={() => setRecordsOpen(true)}
                  aria-haspopup="dialog"
                >
                  <Clock3 size={16} /> 내 기록
                </button>
                {session && (
                  <button
                    className="record-page-delete"
                    disabled={recording || deleting}
                    title={
                      recording
                        ? "녹음 또는 업로드를 마친 후 삭제할 수 있습니다."
                        : undefined
                    }
                    onClick={() => requestDelete(session.id, currentRecordName)}
                    aria-haspopup="dialog"
                  >
                    <Trash2 size={16} /> 기록 삭제
                  </button>
                )}
              </div>
            )}
          </div>
          {error && (
            <div role="alert" className="error-banner">
              <span>{errorMessage(error)}</span>
              <button
                className="icon-button"
                aria-label="오류 닫기"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {!authenticated ? (
            <section className="panel auth-panel">
              <KeyRound size={24} />
              <h2>워크스페이스에 로그인</h2>
              <p>초대 링크로 접속하거나 워크스페이스 접속 키를 입력하세요.</p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  connect(key);
                  setKey("");
                  setError("");
                }}
              >
                <input
                  aria-label="워크스페이스 접속 키"
                  autoComplete="off"
                  type="password"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder="워크스페이스 접속 키"
                />
                <button className="primary" disabled={!key.trim()}>
                  로그인
                </button>
              </form>
            </section>
          ) : (
            <>
              {health?.engine === "fake" && (
                <div className="notice">
                  검증 환경에서는 실제 음성 인식 대신 예시 결과가 표시됩니다.
                </div>
              )}
              {health?.engine === "real" &&
                health.workers.asr.ready &&
                !health.workers.diar.ready && (
                  <div className="notice">
                    현재 화자를 구분할 수 없어 전사 내용만 제공됩니다. 화자
                    이름은 직접 지정할 수 있습니다.
                  </div>
                )}
              <div className="workspace-grid">
                <div className="workspace-main">
                  {mode === "file" ? (
                    <FileTranscriptionPage
                      health={health}
                      session={session}
                      onSession={receiveSession}
                      onError={setError}
                      onClear={() => setSession(null)}
                      file={selectedFile}
                      onFile={setSelectedFile}
                      onAssociate={(sid, file) =>
                        setLocalFiles((current) => ({
                          ...current,
                          [sid]: file,
                        }))
                      }
                      onUploading={setRecording}
                    />
                  ) : (
                    <LiveTranscriptionPage
                      health={health}
                      session={session}
                      onSession={receiveSession}
                      onError={setError}
                      onRecording={setRecording}
                    />
                  )}
                  {mode === "file" && (selectedFile || session) && (
                    <div className="meeting-file-player">
                      <LocalAudioPlayer
                        key={session?.id || "new-file"}
                        file={
                          session
                            ? (localFiles[session.id] ?? null)
                            : selectedFile
                        }
                        session={session}
                        onFile={(file) => {
                          if (session) {
                            if (
                              session.source_file &&
                              (session.source_file.name !== file.name ||
                                session.source_file.size !== file.size)
                            ) {
                              setError(
                                "이 대본을 만들 때 올린 것과 같은 원본 파일을 선택해 주세요.",
                              );
                              return;
                            }
                            setLocalFiles((current) => ({
                              ...current,
                              [session.id]: file,
                            }));
                          } else setSelectedFile(file);
                        }}
                        seek={
                          seek &&
                          session?.utterances.some(
                            (u) => u.utterance_id === seek.utteranceId,
                          )
                            ? seek
                            : null
                        }
                        onPosition={setPlaybackMs}
                        syncEnabled={syncEnabled}
                        onSyncChange={setSyncEnabled}
                        highlightWords={highlightWords}
                        onHighlightWordsChange={setHighlightWords}
                      />
                    </div>
                  )}
                  {!!session?.warnings.length && (
                    <div className="notice">
                      {Array.from(
                        new Set(session.warnings.map(warningMessage)),
                      ).join(" ")}
                    </div>
                  )}
                  <TranscriptView
                    key={session?.id || "new-transcript"}
                    session={session}
                    refresh={refresh}
                    onError={setError}
                    onSession={receiveSession}
                    onDelete={() =>
                      session && requestDelete(session.id, currentRecordName)
                    }
                    deleteDisabled={recording || deleting}
                    canPlay={
                      mode === "file" &&
                      !!(session ? localFiles[session.id] : selectedFile)
                    }
                    syncEnabled={syncEnabled}
                    highlightWords={highlightWords}
                    playbackMs={playbackMs}
                    onSeek={seekToUtterance}
                  />
                </div>
                <MeetingAssistant session={session} />
              </div>
            </>
          )}
        </div>
      </main>
      {recordsOpen && (
        <RecordsDialog onClose={() => setRecordsOpen(false)}>
          {recordsList}
        </RecordsDialog>
      )}
      {deleteTarget && (
        <DeleteRecordDialog
          name={deleteTarget.name}
          busy={deleting}
          error={deleteError}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => void deleteRecord()}
        />
      )}
    </div>
  );
}
