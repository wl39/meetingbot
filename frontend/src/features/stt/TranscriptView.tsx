import {
  Fragment,
  memo,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { FileText, Pencil, Check, X, AudioLines, Play } from "lucide-react";
import { api, time, type Session, type Utterance } from "./api";
import { SpeakerEditor } from "./SpeakerEditor";
import { TranscriptText } from "./TranscriptText";
import { TranscriptToolbar } from "./TranscriptToolbar";
import { activeRangeId, buildScript, type PlaybackRange } from "./script";
const Row = memo(function Row({
  u,
  session,
  refresh,
  onError,
  canPlay,
  onSeek,
  playbackMs,
  highlightWords,
}: {
  u: Utterance;
  session: Session;
  refresh: () => void;
  onError: (s: string) => void;
  canPlay: boolean;
  onSeek: (utterance: PlaybackRange) => void;
  playbackMs: number;
  highlightWords: boolean;
}) {
  const [edit, setEdit] = useState(false),
    [text, setText] = useState(u.text),
    [speaker, setSpeaker] = useState(u.speaker_id || ""),
    [revision, setRevision] = useState(u.revision),
    [original, setOriginal] = useState({
      text: u.text,
      speaker: u.speaker_id || "",
    });
  const index = Object.keys(session.speakers).indexOf(u.speaker_id || "");
  async function save() {
    const patch: Record<string, unknown> = { base_revision: revision };
    if (text !== original.text) patch.text = text;
    if (speaker !== original.speaker) patch.speaker_id = speaker || null;
    if (Object.keys(patch).length === 1) {
      setEdit(false);
      return;
    }
    try {
      await api(`/sessions/${session.id}/utterances/${u.utterance_id}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      setEdit(false);
      refresh();
    } catch (e) {
      onError(
        String(e).includes("REVISION_CONFLICT")
          ? "대본이 업데이트되었습니다. 취소 후 최신 내용에서 다시 수정해 주세요."
          : String(e),
      );
    }
  }
  return (
    <article
      data-range-id={u.utterance_id}
      className={`utterance ${u.status === "partial" ? "partial" : ""} ${canPlay && playbackMs >= u.start_ms && playbackMs < u.end_ms ? "playing" : ""}`}
    >
      <div className="utterance-playback">
        <button
          className="utterance-play"
          disabled={!canPlay}
          aria-label={`${time(u.start_ms)} 발화 재생`}
          title={
            canPlay ? "발화 재생 및 파형 강조" : "원본 음성 파일을 연결하세요"
          }
          onClick={() => onSeek(u)}
        >
          <Play size={13} fill="currentColor" />
        </button>
        <button
          className="utterance-time"
          disabled={!canPlay}
          title={canPlay ? "이 구간 재생" : "원본 음성 파일을 연결하세요"}
          onClick={() => onSeek(u)}
        >
          {time(u.start_ms)}
          <small>{time(u.end_ms)}</small>
        </button>
      </div>
      <div className="utterance-body">
        <div className="utterance-meta">
          <span className={`speaker-avatar color-${Math.max(0, index) % 8}`}>
            {index >= 0 ? String.fromCharCode(65 + index) : "?"}
          </span>
          <b>{session.speakers[u.speaker_id || ""] || "발언자"}</b>
          {u.status === "partial" && <span className="tag">입력 중</span>}
          {u.status === "corrected" && <span className="tag">직접 수정</span>}
          {u.overlap && <span className="tag warning">겹친 발화</span>}
        </div>
        {edit ? (
          <div className="edit-fields">
            <textarea
              aria-label="발언 수정"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <select
              aria-label="화자 수정"
              value={speaker}
              onChange={(e) => setSpeaker(e.target.value)}
            >
              <option value="">미확정</option>
              {Object.entries(session.speakers).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
            <button onClick={save}>
              <Check size={15} />
              저장
            </button>
            <button onClick={() => setEdit(false)}>
              <X size={15} />
              취소
            </button>
          </div>
        ) : (
          <p>
            <TranscriptText
              utterance={u}
              playbackMs={highlightWords ? playbackMs : -1}
              onSeek={canPlay && highlightWords ? onSeek : undefined}
            />
          </p>
        )}
      </div>
      {!edit && (
        <button
          className="icon-button edit-button"
          title="발언 수정"
          onClick={() => {
            setText(u.text);
            setSpeaker(u.speaker_id || "");
            setRevision(u.revision);
            setOriginal({ text: u.text, speaker: u.speaker_id || "" });
            setEdit(true);
          }}
        >
          <Pencil size={15} />
        </button>
      )}
    </article>
  );
});
export function TranscriptView({
  session,
  refresh,
  onError,
  onSession,
  onDelete,
  deleteDisabled,
  canPlay,
  onSeek,
  playbackMs,
  syncEnabled,
  highlightWords,
}: {
  session: Session | null;
  refresh: () => void;
  onError: (s: string) => void;
  onSession: (s: Session) => void;
  onDelete: () => void;
  deleteDisabled: boolean;
  canPlay: boolean;
  onSeek: (utterance: PlaybackRange) => void;
  playbackMs: number;
  syncEnabled: boolean;
  highlightWords: boolean;
}) {
  const [scriptMode, setScriptMode] = useState(false);
  const tabId = useId();
  const list = useRef<HTMLDivElement>(null);
  const canConvert =
    !!session?.utterances.length &&
    (session.state === "COMPLETED" || session.state === "PARTIAL");
  const showScript = scriptMode && canConvert;
  const wordSeekEnabled = canPlay && syncEnabled && highlightWords;
  // Word controls need a non-interactive parent, so they never nest in the
  // whole-block playback button or trigger a second seek to the block start.
  const ScriptContainer = wordSeekEnabled ? "article" : "button";
  const ScriptMeta = wordSeekEnabled ? "button" : "span";
  const blocks = useMemo(
    () => (showScript ? buildScript(session?.utterances ?? []) : []),
    [showScript, session?.utterances],
  );
  const activeId = canPlay
    ? activeRangeId(
        showScript ? blocks : (session?.utterances ?? []),
        playbackMs,
      )
    : undefined;
  useEffect(() => {
    if (!syncEnabled || !activeId || !list.current) return;
    const container = list.current;
    const row = Array.from(container.children).find(
      (element) => (element as HTMLElement).dataset.rangeId === activeId,
    );
    if (!row) return;
    const bounds = container.getBoundingClientRect();
    const target = row.getBoundingClientRect();
    // Scroll only the transcript pane; keep the player and page in place.
    container.scrollTo({
      top:
        container.scrollTop +
        target.top -
        bounds.top -
        Math.max(0, (container.clientHeight - target.height) / 2),
      behavior: "instant",
    });
  }, [activeId, syncEnabled, showScript]);
  useEffect(() => {
    if (!syncEnabled || !highlightWords || !canPlay || !list.current) return;
    const container = list.current;
    const word = container.querySelector(".current-word");
    if (!word) return;
    const bounds = container.getBoundingClientRect();
    const target = word.getBoundingClientRect();
    if (target.top < bounds.top + 20 || target.bottom > bounds.bottom - 20) {
      container.scrollTo({
        top:
          container.scrollTop +
          target.top -
          bounds.top -
          container.clientHeight / 2,
        behavior: "instant",
      });
    }
  }, [playbackMs, syncEnabled, highlightWords, canPlay, showScript]);
  return (
    <section
      className={`panel transcript ${session?.utterances.length ? "" : "is-empty"}`}
    >
      <div className="panel-heading">
        <div>
          <h2>
            <FileText size={19} />
            전사 대본
          </h2>
          <p>
            {session
              ? `${session.utterances.length}개 발언 · ${Object.keys(session.speakers).length}명 화자`
              : "음성의 흐름을 대본으로 확인하세요"}
          </p>
        </div>
      </div>
      <TranscriptToolbar
        session={session}
        mode={showScript ? "script" : "utterance"}
        canConvert={canConvert}
        onModeChange={(mode) => setScriptMode(mode === "script")}
        id={tabId}
        description={
          showScript
            ? `${blocks.length}개 대화 · 화자별로 읽어보세요.${canPlay ? (wordSeekEnabled ? " 단어를 누르면 그 위치부터 재생합니다." : " 대본을 누르면 재생합니다.") : ""}`
            : canConvert
              ? "발화마다 시간과 화자를 확인하고, 내용을 수정할 수 있습니다."
              : "발언 시간과 화자를 확인하세요. 정리가 끝나면 대본 보기로 읽을 수 있습니다."
        }
      />
      {session && (
        <SpeakerEditor
          sid={session.id}
          speakers={session.speakers}
          refresh={refresh}
          onError={onError}
        />
      )}
      {!session?.utterances.length ? (
        <div
          className="empty-transcript"
          role="tabpanel"
          id={`${tabId}-panel`}
          aria-labelledby={`${tabId}-utterance`}
        >
          <div className="empty-icon">
            <AudioLines size={30} strokeWidth={1.4} />
          </div>
          <h3>아직 대본이 없습니다</h3>
          <p>
            파일을 전사하거나 마이크로 녹음을 시작하세요.
            <br />
            말한 내용과 화자가 여기에 표시됩니다.
          </p>
          <div className="skeleton-line" />
          <div className="skeleton-line short" />
        </div>
      ) : (
        <div
          className="utterances"
          ref={list}
          role="tabpanel"
          id={`${tabId}-panel`}
          aria-labelledby={`${tabId}-${showScript ? "script" : "utterance"}`}
          tabIndex={0}
        >
          {showScript
            ? blocks.map((block) => (
                <ScriptContainer
                  key={block.utterance_id}
                  data-range-id={block.utterance_id}
                  className={`script-block ${activeId === block.utterance_id ? "playing" : ""}`}
                  aria-current={
                    activeId === block.utterance_id ? "true" : undefined
                  }
                  {...(!wordSeekEnabled
                    ? {
                        disabled: !canPlay,
                        onClick: () => onSeek(block),
                      }
                    : {})}
                >
                  <ScriptMeta
                    className={`script-meta ${wordSeekEnabled ? "script-play" : ""}`}
                    {...(wordSeekEnabled
                      ? {
                          type: "button" as const,
                          onClick: () => onSeek(block),
                          title: "대본 처음부터 재생",
                        }
                      : {})}
                  >
                    <b>
                      {session.speakers[block.speaker_id || ""] || "발언자"}
                    </b>
                    <span>
                      {time(block.start_ms)} ~ {time(block.end_ms)}
                    </span>
                    <Play size={14} />
                  </ScriptMeta>
                  <span className="script-text">
                    {block.utterances
                      .filter((u) => u.text.trim())
                      .map((u, index) => (
                        <Fragment key={u.utterance_id}>
                          {index > 0 && " "}
                          <TranscriptText
                            utterance={u}
                            trim
                            onSeek={wordSeekEnabled ? onSeek : undefined}
                            playbackMs={
                              canPlay &&
                              syncEnabled &&
                              highlightWords &&
                              playbackMs >= u.start_ms &&
                              playbackMs < u.end_ms
                                ? playbackMs
                                : -1
                            }
                          />
                        </Fragment>
                      ))}
                  </span>
                  {block.includesUnknown && (
                    <small>같은 화자 사이의 짧은 미확정 발화 포함</small>
                  )}
                </ScriptContainer>
              ))
            : session.utterances.map((u) => (
                <Row
                  key={u.utterance_id}
                  u={u}
                  session={session}
                  refresh={refresh}
                  onError={onError}
                  canPlay={canPlay}
                  onSeek={onSeek}
                  playbackMs={
                    canPlay && playbackMs >= u.start_ms && playbackMs < u.end_ms
                      ? playbackMs
                      : -1
                  }
                  highlightWords={syncEnabled && highlightWords}
                />
              ))}
        </div>
      )}
      {session && (
        <div className="transcript-footer">
          {session.audio_retained ? (
            <>
              <button
                onClick={async () => {
                  try {
                    const r = await api<{ session_id: string }>(
                      `/sessions/${session.id}/reprocess`,
                      { method: "POST" },
                    );
                    onSession(await api<Session>(`/sessions/${r.session_id}`));
                  } catch (e) {
                    onError(String(e));
                  }
                }}
              >
                원음으로 재처리
              </button>
            </>
          ) : (
            <span>원본 음성을 들으며 대본을 확인할 수 있습니다.</span>
          )}
          <button
            className="danger-text"
            disabled={deleteDisabled}
            title={
              deleteDisabled
                ? "녹음 또는 업로드를 마친 후 삭제할 수 있습니다."
                : undefined
            }
            onClick={onDelete}
            aria-haspopup="dialog"
          >
            기록 삭제
          </button>
        </div>
      )}
    </section>
  );
}
