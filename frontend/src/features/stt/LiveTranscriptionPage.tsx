import { useEffect, useRef, useState } from "react";
import { Mic, Square, Radio, LoaderCircle } from "lucide-react";
import {
  api,
  modelReady,
  token,
  time,
  states,
  type Health,
  type Session,
} from "./api";
import { packFrame } from "./audio-worklet";
import { Controls } from "./Controls";
import { useTranscriptionOptions } from "./useTranscriptionOptions";
import { useOnboarding } from "../onboarding/context";
import { recordingWav } from "./tutorial-audio";

type Capture = {
  sessionId: string;
  lastSession: Session | null;
  tutorialChunks: Float32Array[] | null;
  socket: WebSocket;
  context: AudioContext;
  stream: MediaStream;
  node: AudioWorkletNode;
  sequence: number;
  sample: number;
  stopping: boolean;
  timer?: number;
  limit?: number;
};
export function LiveTranscriptionPage({
  health,
  session,
  onSession,
  onError,
  onRecording,
}: {
  health: Health | null;
  session: Session | null;
  onSession: (s: Session) => void;
  onError: (s: string) => void;
  onRecording: (v: boolean) => void;
}) {
  const [state, setState] = useState("idle"),
    [elapsed, setElapsed] = useState(0),
    [level, setLevel] = useState(0),
    [device, setDevice] = useState("기본 마이크");
  const [options, setOptions] = useTranscriptionOptions(
    health,
    state !== "idle",
  );
  const capture = useRef<Capture | null>(null);
  const tutorial = useOnboarding();
  const currentTutorial = useRef(tutorial);
  currentTutorial.current = tutorial;
  const recordedAudio = useRef<{ sessionId: string; file: File } | null>(null);
  useEffect(() => {
    const recording = recordedAudio.current;
    if (!session || !tutorial?.active || recording?.sessionId !== session.id) {
      recordedAudio.current = null;
      return;
    }
    if (
      tutorial?.active &&
      recording &&
      session &&
      recording.sessionId === session.id &&
      ["COMPLETED", "PARTIAL"].includes(session.state) &&
      session.utterances.some(
        (utterance) =>
          !["partial", "retracted"].includes(utterance.status) &&
          !!utterance.text.trim(),
      )
    ) {
      tutorial.reportVoice(recording.file, recording.sessionId);
      recordedAudio.current = null;
    }
  }, [session, tutorial?.active, tutorial?.reportVoice]);
  const liveSeconds = health?.limits.live_seconds ?? 300;
  const callbacks = useRef({ onSession, onError, onRecording });
  callbacks.current = { onSession, onError, onRecording };
  function cleanup() {
    const c = capture.current;
    if (c) {
      if (c.tutorialChunks?.length) {
        recordedAudio.current = {
          sessionId: c.sessionId,
          file: recordingWav(c.tutorialChunks, c.context.sampleRate),
        };
        c.tutorialChunks = null;
        if (
          currentTutorial.current?.active &&
          c.lastSession &&
          ["COMPLETED", "PARTIAL"].includes(c.lastSession.state) &&
          c.lastSession.utterances.some(
            (utterance) =>
              !["partial", "retracted"].includes(utterance.status) &&
              !!utterance.text.trim(),
          )
        ) {
          currentTutorial.current.reportVoice(
            recordedAudio.current.file,
            recordedAudio.current.sessionId,
          );
          recordedAudio.current = null;
        }
      }
      clearInterval(c.timer);
      clearTimeout(c.limit);
      c.stream.getTracks().forEach((t) => t.stop());
      c.node.disconnect();
      void c.context.close();
      capture.current = null;
    }
    setLevel(0);
    callbacks.current.onRecording(false);
  }
  useEffect(
    () => () => {
      const c = capture.current;
      if (c) {
        c.stream.getTracks().forEach((t) => t.stop());
        c.socket.close();
        clearInterval(c.timer);
        clearTimeout(c.limit);
        void c.context.close();
        capture.current = null;
      }
    },
    [],
  );
  function stop() {
    const c = capture.current;
    if (!c || c.stopping) return;
    c.stopping = true;
    clearTimeout(c.limit);
    clearInterval(c.timer);
    setState("finalizing");
    c.node.port.postMessage("stop");
  }
  async function start() {
    recordedAudio.current = null;
    callbacks.current.onError("");
    setState("starting");
    callbacks.current.onRecording(true);
    let media: MediaStream | undefined,
      context: AudioContext | undefined,
      socket: WebSocket | undefined;
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("마이크를 사용하려면 HTTPS 주소로 접속해 주세요.");
      }
      // Resume in the original tap handler so mobile Safari retains user activation.
      context = new AudioContext();
      const resume = context.resume();
      media = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        },
        video: false,
      });
      await resume;
      await context.audioWorklet.addModule("/audio-worklet.js");
      const session = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify(options),
      });
      callbacks.current.onSession(session);
      const node = new AudioWorkletNode(context, "pcm-collector");
      socket = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/stt/sessions/${session.id}/stream`,
        token() ? ["stt", `stt.${token()}`] : ["stt"],
      );
      const c: Capture = {
        sessionId: session.id,
        lastSession: session,
        tutorialChunks: tutorial?.active ? [] : null,
        socket,
        context,
        stream: media,
        node,
        sequence: 0,
        sample: 0,
        stopping: false,
      };
      capture.current = c;
      let began = false;
      socket.onopen = () =>
        socket!.send(
          JSON.stringify({
            type: "start",
            stream_id: crypto.randomUUID(),
            sample_rate: context!.sampleRate,
            channels: 1,
            encoding: "f32le",
          }),
        );
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === "ack" && message.action === "start") {
          began = true;
          const started = performance.now();
          setElapsed(0);
          setState("recording");
          callbacks.current.onRecording(true);
          setDevice("마이크 연결됨");
          context!.createMediaStreamSource(media!).connect(node);
          node.connect(context!.destination);
          c.timer = window.setInterval(
            () => setElapsed(performance.now() - started),
            200,
          );
          c.limit = window.setTimeout(
            stop,
            Math.max(1, liveSeconds - 1) * 1000,
          );
        }
        if (message.type === "snapshot" && message.session) {
          c.lastSession = message.session;
          callbacks.current.onSession(message.session);
        }
        if (message.type === "error") {
          callbacks.current.onError(
            "음성을 처리하지 못했습니다. 연결을 확인한 뒤 녹음을 다시 시작해 주세요.",
          );
          socket!.close();
        }
        if (message.type === "completed" || message.type === "deleted") {
          setState("idle");
          cleanup();
          socket!.close();
        }
      };
      socket.onerror = () =>
        callbacks.current.onError(
          "실시간 연결에 실패했습니다. 인터넷 연결을 확인하고 다시 로그인해 주세요.",
        );
      socket.onclose = () => {
        if (capture.current) {
          if (began && !c.stopping)
            callbacks.current.onError(
              "연결이 끊겨 녹음을 멈췄습니다. 기록된 내용을 확인하고 다시 시작해 주세요.",
            );
          cleanup();
          setState("idle");
        }
      };
      node.port.onmessage = ({ data }) => {
        if (data.type === "audio") {
          const samples = data.samples as Float32Array;
          if (socket!.readyState !== WebSocket.OPEN) return;
          if (socket!.bufferedAmount > 1024 * 1024) {
            callbacks.current.onError(
              "연결이 원활하지 않아 녹음을 멈췄습니다. 마지막 내용이 빠졌을 수 있으니 대본을 확인해 주세요.",
            );
            socket!.close();
            return;
          }
          const remaining =
            Math.floor(context!.sampleRate * liveSeconds) - c.sample;
          const chunk = samples.subarray(0, Math.max(0, remaining));
          if (chunk.length) {
            c.tutorialChunks?.push(chunk.slice());
            socket!.send(packFrame(c.sequence++, c.sample, chunk));
            c.sample += chunk.length;
            let sum = 0;
            chunk.forEach((v) => (sum += v * v));
            setLevel(Math.min(1, Math.sqrt(sum / chunk.length) * 8));
          }
          if (remaining <= samples.length) stop();
        }
        if (data.type === "flushed") {
          // MessagePort preserves order: the final partial PCM frame is queued before stop.
          if (socket!.readyState === WebSocket.OPEN)
            socket!.send(
              JSON.stringify({ type: "stop", last_sequence: c.sequence - 1 }),
            );
          media!.getTracks().forEach((track) => track.stop());
          node.disconnect();
          void context!.suspend();
          setLevel(0);
        }
      };
    } catch (e) {
      media?.getTracks().forEach((t) => t.stop());
      if (context) void context.close();
      socket?.close();
      capture.current = null;
      setState("idle");
      callbacks.current.onRecording(false);
      callbacks.current.onError(
        e instanceof Error && e.name === "NotAllowedError"
          ? "마이크 권한이 필요합니다. 브라우저의 마이크 접근을 허용해 주세요."
          : String(e),
      );
    }
  }
  const active = state !== "idle";
  return (
    <section className="panel input-panel">
      <div className="panel-heading">
        <div>
          <h2>
            <Radio size={19} />
            실시간 음성
          </h2>
          <p>말하는 내용을 바로 대본으로 확인하세요.</p>
        </div>
        <span className="subtle-badge">최대 {liveSeconds / 60}분</span>
      </div>
      <div
        className={`microphone-stage ${state === "recording" ? "recording" : ""}`}
      >
        <div
          className="mic-orb"
          style={{
            boxShadow: `0 0 0 ${10 + level * 25}px rgba(30,112,91,.07)`,
          }}
        >
          <Mic size={30} />
        </div>
        <strong>{time(elapsed)}</strong>
        <span>
          {state === "recording"
            ? level > 0.05
              ? "음성 입력 감지 중"
              : "말씀해 주세요"
            : state === "finalizing"
              ? "대본을 마무리하고 있습니다"
              : state === "starting"
                ? "마이크 연결 중"
                : "녹음 버튼을 누르고 말씀해 주세요"}
        </span>
        <small>{device}</small>
      </div>
      <Controls
        value={options}
        onChange={setOptions}
        disabled={active}
        health={health}
      />
      <div className="action-row">
        <span>녹음 중에는 이 화면을 열어 두세요.</span>
        {state === "recording" ? (
          <button className="stop" onClick={stop}>
            <Square size={15} fill="currentColor" />
            녹음 중지
          </button>
        ) : (
          <button
            className="primary"
            disabled={
              active ||
              !modelReady(health, options.model) ||
              !health?.workers.vad?.ready ||
              !!health?.active_session
            }
            onClick={start}
          >
            {active ? (
              <LoaderCircle className="spin" size={17} />
            ) : (
              <Mic size={17} />
            )}
            녹음 시작
          </button>
        )}
      </div>
      {session && (
        <div className="live-metrics" role="status">
          <span>{states[session.state]}</span>
        </div>
      )}
    </section>
  );
}
