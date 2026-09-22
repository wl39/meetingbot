/**
 * UI coverage for deleting personal microphone and file records.
 * Every API request is intercepted with deterministic fixtures; no real records,
 * microphone, uploads or service data are created or deleted.
 * Run against an existing frontend: node scripts/record_deletion_smoke.mjs
 */
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = path.join(root, ".runtime", "record-deletion-qa");
const base = process.env.RECORDS_QA_URL || "http://127.0.0.1:5173";
await mkdir(output, { recursive: true });
const workspace = {
  id: "c".repeat(32),
  name: "회의에 사용할 제품팀 참고 문서와 지난 회의 자료",
  state: "READY",
  document_count: 65,
  active_revision_id: "revision",
  consent: "fixture",
  can_manage: true,
  visibility: "private",
  access_state: "AVAILABLE",
  source: { kind: "upload", label: "문서" },
  latest_job: null,
};
const diagnostics = {
  model: { state: "READY" },
  llm: { global_allowed: true, configured: true, provider_id: "fixture" },
  history_days: 30,
  limits: {},
};
const session = {
  id: "ui-session",
  mode: "file",
  state: "COMPLETED",
  snapshot_revision: 1,
  source_file: {
    name: "회의_주간_진행_사항_및_결정해야할_안건_정리_매우_긴_음성파일_이름.mp3",
    size: 1000,
  },
  utterances: [
    {
      utterance_id: "u1",
      revision: 1,
      start_ms: 0,
      end_ms: 1000,
      text: "제품팀 회의는 매주 월요일에 진행합니다. 이번 주에 출시할 기능과 고객 피드백을 함께 확인해 주세요.",
      speaker_id: "speaker-a",
      status: "final",
      speaker_status: "final",
      overlap: false,
      manual_fields: [],
      words: [],
    },
  ],
  speakers: {
    "speaker-a": "제품기획팀_김이름_긴이름표시테스트_회의진행담당자",
  },
  warnings: [],
  metrics: {},
  audio_retained: false,
};
const report = {
  synthetic: true,
  limitations:
    "All API requests use fixtures; no real service data changes or physical microphone access.",
  checks: [],
  errors: [],
  unexpected: [],
};
let deleteCalls = [];
let failDelete = false;
const sessions = new Map([
  ["ui-session", session],
  [
    "mic-session",
    {
      ...session,
      id: "mic-session",
      mode: "microphone",
      source_file: undefined,
    },
  ],
  [
    "processing-session",
    {
      ...session,
      id: "processing-session",
      state: "TRANSCRIBING",
      utterances: [],
      source_file: { name: "처리중인 파일.mp3", size: 1000 },
    },
  ],
]);
sessions.set("other-session", { ...session, id: "other-session" });
const initialRecords = [...sessions.values()].map((item) => ({
  id: item.id,
  mode: item.mode,
  state: item.state,
  created_at: 1789000000,
}));
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROME_PATH ||
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
});
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (e) => report.errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem(
      "meetingbot:getting-started:v1:ui-qa",
      JSON.stringify({
        step: "dismissed",
        source: "own",
        workspaceId: null,
        workspaceName: "",
        query: "",
        voicePrompt: "",
        searched: false,
        recorded: false,
        uploaded: false,
      }),
    );
    window.WebSocket = class {
      static OPEN = 1;
      readyState = 1;
      send() {}
      close() {}
    };
  });
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    let data = {};
    if (route.request().method() === "DELETE") {
      deleteCalls.push(pathname);
      if (failDelete)
        return route.fulfill({
          status: 403,
          json: { detail: "삭제 권한을 확인할 수 없습니다." },
        });
      sessions.delete(pathname.split("/").at(-1));
      return route.fulfill({ status: 204 });
    }
    if (route.request().method() !== "GET" && pathname !== "/api/events")
      throw new Error("Mutation forbidden: " + pathname);
    if (pathname === "/api/access/session")
      data = {
        authenticated: true,
        role: "visitor",
        account: { id: "ui-qa", label: "UI 확인", role: "visitor" },
        keyless: true,
        demo: false,
        csrf: "fixture",
      };
    else if (pathname === "/api/system/theme") data = { color: "#b85c12" };
    else if (pathname === "/api/events") data = {};
    else if (pathname === "/api/rag/auth/session") data = { csrf: "fixture" };
    else if (pathname === "/api/stt/health")
      data = {
        engine: "real",
        default_model: "small",
        active_session: null,
        management_busy: false,
        limits: { file_mb: 30, file_seconds: 300, live_seconds: 300 },
        environment: {},
        workers: {
          asr: { ready: true },
          diar: { ready: true },
          vad: { ready: true },
        },
      };
    else if (
      pathname === "/api/stt/meeting/workspaces" ||
      pathname === "/api/rag/workspaces"
    )
      data = [workspace];
    else if (
      pathname === "/api/stt/meeting/diagnostics" ||
      pathname === "/api/rag/diagnostics"
    )
      data = diagnostics;
    else if (pathname === "/api/stt/sessions") data = initialRecords;
    else if (/^\/api\/stt\/sessions\/[^/]+$/.test(pathname)) {
      data = sessions.get(pathname.split("/").at(-1));
      if (!data)
        return route.fulfill({ status: 404, json: { detail: "NOT_FOUND" } });
    } else if (pathname.endsWith("/subscription"))
      data = { enabled: false, workspace_id: null, revision_id: null };
    else if (pathname.endsWith("/jobs"))
      data = {
        jobs: [],
        total: 0,
        next_cursor: null,
        scheduler: {
          mode: "NORMAL",
          pq_pending: 0,
          sq_pending: 0,
          filter_pending: 0,
          oldest_sq_seconds: 0,
        },
        policy: {},
      };
    else if (pathname.endsWith("/export/preview"))
      data = {
        content: "[00:00] 제품기획팀\n제품팀 회의는 매주 월요일에 진행합니다.",
        truncated: false,
        format: "txt",
        view: "utterance",
        filename: "대본.txt",
      };
    else report.unexpected.push(pathname);
    await route.fulfill({ json: data });
  });
  async function check(label, width, modal = false) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForTimeout(200);
    report.checks.push({
      label,
      width,
      ...(await page.evaluate((modal) => {
        const target = modal
          ? document.querySelector("dialog")
          : document.documentElement;
        const selectors = modal
          ? [
              ".export-dialog-heading",
              ".export-dialog-body",
              ".export-dialog-footer",
            ]
          : [
              ".input-panel .panel-heading",
              ".controls",
              ".action-row",
              ".meeting-controls",
              ".transcript-tab-row",
              ".transcript-mode-description",
            ];
        const overflow = [...target.querySelectorAll("*")]
          .filter(
            (e) =>
              e.clientWidth &&
              e.scrollWidth > e.clientWidth + 2 &&
              !["SCRIPT", "STYLE", "SELECT", "INPUT"].includes(e.tagName) &&
              !["auto", "scroll", "hidden", "clip"].includes(
                getComputedStyle(e).overflowX,
              ),
          )
          .map((e) => ({
            class: e.className,
            width: e.clientWidth,
            scroll: e.scrollWidth,
          }));
        return {
          documentWidth: document.documentElement.scrollWidth,
          viewport: innerWidth,
          overflow,
          padding: selectors.flatMap((selector) =>
            [...document.querySelectorAll(selector)]
              .filter((e) => e.getBoundingClientRect().width)
              .map((e) => ({
                selector,
                left: getComputedStyle(e).paddingLeft,
                right: getComputedStyle(e).paddingRight,
              })),
          ),
          modal: modal
            ? {
                width: target.getBoundingClientRect().width,
                height: target.getBoundingClientRect().height,
              }
            : undefined,
        };
      }, modal)),
    });
    assert.equal(
      report.checks.at(-1).documentWidth,
      width,
      "No horizontal page overflow",
    );
    assert.deepEqual(
      report.checks.at(-1).overflow,
      [],
      "No uncontained content in the dialog",
    );
    await page.screenshot({
      path: `${output}/${label}-${width}.png`,
      fullPage: !modal,
    });
  }

  await page.goto(base + "/");
  await page.locator(".sidebar .record-open").first().click();
  await page.locator(".utterance").waitFor();
  await page.locator(".record-page-delete").click();
  await page.getByRole("button", { name: "취소", exact: true }).click();
  assert.equal(deleteCalls.length, 0);
  report.checks.push("Cancel leaves the record unchanged");
  await page
    .locator(".sidebar .record-item")
    .last()
    .locator(".record-delete")
    .click();
  await page.locator(".record-confirm-delete").click();
  await page.locator(".record-confirm-dialog").waitFor({ state: "detached" });
  assert.equal(await page.locator(".utterance").count(), 1);
  assert.equal(await page.locator(".sidebar .record-item").count(), 3);
  report.checks.push(
    "Deleting an unselected sidebar record preserves the open transcript",
  );
  await page.locator(".record-page-delete").click();
  failDelete = true;
  await page.locator(".record-confirm-delete").click();
  await page.locator(".record-confirm-error").waitFor();
  assert.equal(await page.locator(".sidebar .record-item").count(), 3);
  assert.equal(await page.locator(".utterance").count(), 1);
  report.checks.push(
    "Delete failure keeps the selected transcript and records and shows an inline error",
  );
  failDelete = false;
  await page.locator(".record-confirm-delete").click();
  await page.locator(".record-confirm-dialog").waitFor({ state: "detached" });
  assert.equal(await page.locator(".sidebar .record-item").count(), 2);
  assert.equal(await page.locator(".utterance").count(), 0);
  assert.equal(await page.locator(".local-player").count(), 0);
  assert.equal(await page.locator(".record-page-delete").count(), 0);
  report.checks.push(
    "Confirmed file delete clears the transcript, player and selected record immediately",
  );
  await page.waitForTimeout(2800);
  assert.equal(await page.locator(".sidebar .record-item").count(), 2);
  report.checks.push("A stale records poll cannot resurrect a deleted record");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator(".record-mobile-toggle").click();
  await page.locator(".records-dialog .record-search input").fill("마이크");
  assert.equal(await page.locator(".records-dialog .record-item").count(), 1);
  await page.locator(".records-dialog .record-open").click();
  await page.locator(".microphone-stage").waitFor();
  assert.equal(await page.locator(".records-dialog").count(), 0);
  report.checks.push(
    "Mobile My records search can reopen a microphone recording",
  );
  await page.locator(".record-page-delete").click();
  for (const width of [390, 320]) await check("delete-dialog", width, true);
  await page.locator(".record-confirm-delete").click();
  await page.locator(".record-confirm-dialog").waitFor({ state: "detached" });
  assert.equal(await page.locator(".record-page-delete").count(), 0);
  report.checks.push(
    "Microphone recording can be deleted from the mobile page",
  );
  await page.locator(".record-mobile-toggle").click();
  await page.locator(".records-dialog .record-search input").fill("");
  await page.locator(".records-dialog .record-open").click();
  await page.locator(".record-page-delete").waitFor();
  assert.equal(await page.locator(".record-page-delete").isEnabled(), true);
  await page.locator(".record-page-delete").click();
  await page.locator(".record-confirm-delete").click();
  await page.locator(".record-confirm-dialog").waitFor({ state: "detached" });
  assert.equal(await page.locator(".record-page-delete").count(), 0);
  report.checks.push(
    "File still being transcribed can be deleted after upload has completed",
  );
  await page.locator(".record-mobile-toggle").click();
  assert.equal(await page.locator(".records-dialog .record-item").count(), 0);
  for (const width of [390, 320]) await check("records-empty", width, true);
  assert.equal(report.errors.length, 0);
  assert.equal(report.unexpected.length, 0);
  report.deleteCalls = deleteCalls;
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally {
  await browser.close();
}
