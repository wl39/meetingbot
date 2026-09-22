import { accessHeaders } from "./access";
import { workspacePath } from "./navigation";

type Action =
  | "click"
  | "change"
  | "submit"
  | "navigation"
  | "error"
  | "unhandledrejection"
  | "pagehide"
  | "play"
  | "pause"
  | "ended"
  | "seeked";
type Event = { action: Action; page: string; target: string };
let queue: Event[] = [];
let ready = false;
let sending = false;
let installed = false;

// Structural position only: no labels, input values, filenames, URLs or error messages.
export function eventTarget(target: EventTarget | null): string {
  if (!(target instanceof Element)) return "window";
  const parts: string[] = [];
  let element: Element | null =
    target.closest("button,a,input,select,textarea,form,audio,video") || target;
  while (element && parts.length < 8) {
    const tag = element.tagName.toLowerCase();
    if (!/^[a-z]{1,16}$/.test(tag)) break;
    const index = element.parentElement
      ? Array.from(element.parentElement.children).indexOf(element)
      : 0;
    parts.unshift(`${tag}:${Math.min(index, 9999)}`);
    element = element.parentElement;
  }
  return parts.join("/") || "window";
}
export function track(action: Action, target: EventTarget | null = null) {
  if (queue.length >= 100) queue.shift();
  queue.push({
    action,
    page: workspacePath(location.pathname),
    target: eventTarget(target),
  });
}
export function setTelemetryReady(value: boolean) {
  ready = value;
}
async function flush() {
  if (!ready || sending || !queue.length) return;
  sending = true;
  const events = queue.splice(0, 50);
  try {
    const response = await fetch("/api/events", {
      method: "POST",
      keepalive: true,
      headers: { ...accessHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ events }),
    });
    if (response.status === 401) ready = false;
  } catch {
    /* Browser telemetry is best effort; never prevent the user's action. */
  } finally {
    sending = false;
  }
}
export function installTelemetry() {
  if (installed) return;
  installed = true;
  for (const action of [
    "click",
    "change",
    "submit",
    "play",
    "pause",
    "ended",
    "seeked",
  ] as const)
    document.addEventListener(
      action,
      (event) => track(action, event.target),
      true,
    );
  window.addEventListener("error", () => track("error"));
  window.addEventListener("unhandledrejection", () =>
    track("unhandledrejection"),
  );
  window.addEventListener("pagehide", () => {
    track("pagehide");
    void flush();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) void flush();
  });
  window.setInterval(() => {
    void flush();
  }, 2000);
}
