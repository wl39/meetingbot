/** Synthetic STT export UX checks; every API request is intercepted. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const base = process.env.STT_UI_BASE || "http://127.0.0.1:5178";
const output = path.join(root, ".runtime/stt-export-qa");
const sid = "synthetic-export";
const formats = ["txt", "srt", "json"];
const views = ["script", "utterance"];
const viewLabel = { script: "대화별 대본", utterance: "발화별 대본" };
const tabLabel = { script: "대본 보기", utterance: "발화별 보기" };
const textA = "오늘 회의에서는 대본 다운로드 방식을 확인하겠습니다.";
const textB = "같은 화자의 발언은 대화별로 이어서 읽을 수 있습니다.";
const textC = "발화별 보기는 개별 발언과 시간 정보를 유지합니다.";
const utterances = [textA, textB, textC].map((text, index) => ({
  utterance_id: `utterance-${index}`,
  revision: 1,
  start_ms: index * 5000,
  end_ms: (index + 1) * 5000,
  speaker_id: index < 2 ? "A" : "B",
  text,
  status: "stable",
  speaker_status: "assigned",
  overlap: false,
  manual_fields: [],
}));
const snapshot = {
  id: sid,
  snapshot_revision: 1,
  mode: "file",
  state: "COMPLETED",
  utterances,
  speakers: { A: "김민수", B: "박지은" },
  warnings: [],
  metrics: {},
  audio_retained: false,
};

function contentFor(view, format) {
  const rows =
    view === "script"
      ? [
          { start: 0, end: 10, speaker: "김민수", text: `${textA} ${textB}` },
          { start: 10, end: 15, speaker: "박지은", text: textC },
        ]
      : utterances.map((u) => ({
          start: u.start_ms / 1000,
          end: u.end_ms / 1000,
          speaker: snapshot.speakers[u.speaker_id],
          text: u.text,
        }));
  const stamp = (seconds) => `00:00:${String(seconds).padStart(2, "0")}`;
  if (format === "json")
    return JSON.stringify(
      {
        export_view: view,
        [view === "script" ? "script_blocks" : "utterances"]: rows.map(
          (row) => ({
            text: row.text,
            speaker: row.speaker,
            start_ms: row.start * 1000,
            end_ms: row.end * 1000,
          }),
        ),
      },
      null,
      2,
    );
  if (format === "srt")
    return rows
      .map(
        (row, i) =>
          `${i + 1}\n${stamp(row.start)},000 --> ${stamp(row.end)},000\n${row.speaker}: ${row.text}`,
      )
      .join("\n\n");
  return rows
    .map(
      (row) =>
        `[${stamp(row.start)} ~ ${stamp(row.end)}] ${row.speaker}\n${row.text}`,
    )
    .join("\n\n");
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

let browser;
let page;
const vite = process.env.STT_UI_BASE
  ? null
  : spawn(
      process.execPath,
      [
        path.join(root, "frontend/node_modules/vite/bin/vite.js"),
        "--host",
        "127.0.0.1",
        "--port",
        "5178",
        "--strictPort",
      ],
      { cwd: path.join(root, "frontend"), stdio: "ignore" },
    );
const errors = [];
const previews = [];
const downloads = [];
let nextPreview;
let nextDownload;

try {
  await mkdir(output, { recursive: true });
  for (let attempt = 0; attempt < 40; attempt++) {
    try {
      await fetch(base);
      break;
    } catch {
      if (attempt === 39) throw new Error("Vite did not start");
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
  }
  browser = await chromium.launch({
    headless: true,
    executablePath:
      process.env.CHROME_PATH ||
      "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.addInitScript(() =>
    sessionStorage.setItem("stt-token", "synthetic"),
  );
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    if (
      pathname === `/api/stt/sessions/${sid}/export/preview` ||
      pathname === `/api/stt/sessions/${sid}/export`
    ) {
      const isPreview = pathname.endsWith("/preview");
      const view = url.searchParams.get("view");
      const format = url.searchParams.get("format");
      assert.ok(views.includes(view), `explicit export view: ${url}`);
      assert.ok(formats.includes(format), `supported format: ${url}`);
      assert.equal(route.request().headers().authorization, "Bearer synthetic");
      (isPreview ? previews : downloads).push({ view, format });
      const behavior = isPreview ? nextPreview : nextDownload;
      if (isPreview) nextPreview = undefined;
      else nextDownload = undefined;
      behavior?.started?.resolve();
      if (behavior?.release) await behavior.release.promise;
      if (behavior?.error) {
        await route.fulfill({ status: 503, json: { detail: behavior.error } });
      } else if (isPreview) {
        await route.fulfill({
          json: {
            content: contentFor(view, format),
            total_items: view === "script" ? 2 : 3,
            preview_items: view === "script" ? 2 : 3,
          },
        });
      } else {
        await route.fulfill({
          contentType: "application/octet-stream",
          body: contentFor(view, format),
        });
      }
      behavior?.finished?.resolve();
      return;
    }
    const data =
      pathname === "/api/stt/health"
        ? {
            engine: "fake",
            active_session: null,
            limits: { file_mb: 4096, file_seconds: 18000 },
            workers: { asr: { ready: true }, diar: { ready: true } },
            environment: { machine: "synthetic" },
          }
        : pathname === "/api/stt/sessions"
          ? [
              {
                id: sid,
                mode: "file",
                state: snapshot.state,
                created_at: 1770000000,
              },
            ]
          : pathname === `/api/stt/sessions/${sid}`
            ? snapshot
            : undefined;
    if (data === undefined) {
      errors.push(`Unexpected API: ${pathname}`);
      await route.abort();
    } else await route.fulfill({ json: data });
  });

  await page.goto(base);
  await page.locator(".history button").click();
  const transcript = page.locator(".transcript");
  const tab = (view) =>
    transcript.getByRole("tab", { name: tabLabel[view], exact: true });
  const exportButton = transcript.getByRole("button", {
    name: "대본 다운로드",
    exact: true,
  });
  const dialog = page.getByRole("dialog", {
    name: "대본 다운로드",
    exact: true,
  });
  const mode = (view) =>
    dialog.getByRole("radio", { name: new RegExp(`^${viewLabel[view]}`) });
  const formatRadio = (format) =>
    dialog.getByRole("radio", { name: format.toUpperCase(), exact: true });
  const submit = (format) =>
    dialog.getByRole("button", {
      name: `${format.toUpperCase()} 다운로드`,
      exact: true,
    });
  const preview = dialog.locator(".export-preview-content");
  const waitPreview = (view, format) =>
    page.waitForFunction(
      (expected) =>
        document.querySelector(".export-preview-content")?.textContent ===
        expected,
      contentFor(view, format),
    );
  const closeDialog = async () => {
    if (await dialog.isVisible())
      await dialog.getByRole("button", { name: "닫기", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
  };
  const openDialog = async (view) => {
    await tab(view).click();
    await exportButton.click();
    await dialog.waitFor();
    assert.equal(
      await mode(view).isChecked(),
      true,
      "download view starts from active tab",
    );
    assert.equal(
      await formatRadio("txt").isChecked(),
      true,
      "each dialog starts with TXT",
    );
    await waitPreview(view, "txt");
  };

  assert.equal(await transcript.getByRole("tablist").count(), 1);
  assert.equal(await transcript.getByRole("tab").count(), 2);
  assert.equal(await tab("utterance").getAttribute("aria-selected"), "true");
  assert.equal(await tab("utterance").getAttribute("tabindex"), "0");
  assert.equal(await tab("script").getAttribute("tabindex"), "-1");
  await tab("utterance").focus();
  for (const [key, view] of [
    ["ArrowLeft", "script"],
    ["ArrowRight", "utterance"],
    ["Home", "script"],
    ["End", "utterance"],
  ]) {
    await page.keyboard.press(key);
    assert.equal(
      await tab(view).getAttribute("aria-selected"),
      "true",
      `${key} selects ${view}`,
    );
    assert.equal(
      await tab(view).evaluate((el) => el === document.activeElement),
      true,
    );
    const panelId = await tab(view).getAttribute("aria-controls");
    assert.ok(panelId, "tab identifies its panel");
    const panel = page.locator(`[id="${panelId}"]`);
    assert.equal(await panel.getAttribute("role"), "tabpanel");
    assert.equal(
      await panel.getAttribute("aria-labelledby"),
      await tab(view).getAttribute("id"),
    );
  }
  const tabBounds = await transcript.getByRole("tablist").boundingBox();
  const buttonBounds = await exportButton.boundingBox();
  assert.ok(
    buttonBounds.x >= tabBounds.x + tabBounds.width - 1,
    "download badge occupies the space to the right of the tabs",
  );
  assert.ok(
    Math.abs(
      buttonBounds.y +
        buttonBounds.height / 2 -
        (tabBounds.y + tabBounds.height / 2),
    ) < 20,
    "tabs and download badge share a row",
  );
  await openDialog("script");
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    await exportButton.evaluate((el) => el === document.activeElement),
    true,
    "Escape restores trigger focus",
  );

  // All format/view combinations use the same selection for preview and file.
  for (const view of views) {
    for (const format of formats) {
      await openDialog(view === "script" ? "utterance" : "script");
      await mode(view).check();
      await formatRadio(format).check();
      await waitPreview(view, format);
      assert.deepEqual(previews.at(-1), { view, format });
      const saved = page.waitForEvent("download");
      await submit(format).click();
      const download = await saved;
      assert.equal(await download.failure(), null);
      assert.ok(download.suggestedFilename().endsWith(`.${format}`));
      assert.equal(
        await readFile(await download.path(), "utf8"),
        contentFor(view, format),
      );
      assert.deepEqual(downloads.at(-1), { view, format });
      await closeDialog();
    }
  }

  // A late preview must never overwrite a more recently selected format.
  const delayedPreview = {
    started: deferred(),
    release: deferred(),
    finished: deferred(),
  };
  await openDialog("script");
  nextPreview = delayedPreview;
  await formatRadio("srt").check();
  await delayedPreview.started.promise;
  await dialog.getByRole("status").waitFor();
  assert.equal(
    await submit("srt").isDisabled(),
    true,
    "download waits for its preview",
  );
  await formatRadio("json").check();
  const currentView = (await mode("script").isChecked())
    ? "script"
    : "utterance";
  await waitPreview(currentView, "json");
  delayedPreview.release.resolve();
  await delayedPreview.finished.promise;
  await page.waitForTimeout(100);
  assert.equal(
    await preview.textContent(),
    contentFor(currentView, "json"),
    "stale SRT response is ignored",
  );
  await closeDialog();

  await openDialog("script");
  nextPreview = { error: "미리보기 검증 오류" };
  await formatRadio("json").check();
  await dialog.getByRole("alert").waitFor();
  assert.equal(
    await submit("json").isEnabled(),
    true,
    "preview failure still allows a file download",
  );
  await formatRadio("srt").check();
  await waitPreview(currentView, "srt");
  assert.equal(
    await dialog.getByRole("alert").count(),
    0,
    "changing format recovers preview failure",
  );

  // Keep the selected export stable and prevent duplicate actions while pending.
  const delayedDownload = { started: deferred(), release: deferred() };
  nextDownload = delayedDownload;
  const pendingDownload = page.waitForEvent("download");
  const beforePending = downloads.length;
  await submit("srt").click();
  await delayedDownload.started.promise;
  assert.equal(
    await dialog
      .getByRole("button", { name: "다운로드 준비 중…", exact: true })
      .isDisabled(),
    true,
  );
  for (const radio of await dialog.getByRole("radio").all())
    assert.equal(await radio.isDisabled(), true);
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    await exportButton.evaluate((el) => el === document.activeElement),
    true,
    "pending download can be dismissed with focus restored",
  );
  assert.equal(downloads.length, beforePending + 1);
  await openDialog("utterance");
  await formatRadio("json").check();
  await waitPreview("utterance", "json");
  delayedDownload.release.resolve();
  assert.equal(await (await pendingDownload).failure(), null);
  await page.waitForTimeout(100);
  assert.equal(
    await dialog.isVisible(),
    true,
    "an earlier download cannot close a newly opened dialog",
  );
  assert.equal(await mode("utterance").isChecked(), true);
  assert.equal(await formatRadio("json").isChecked(), true);
  await closeDialog();

  await openDialog("script");
  nextDownload = { error: "다운로드 검증 오류" };
  await submit("txt").click();
  await dialog.getByRole("alert").waitFor();
  assert.equal(
    await dialog.isVisible(),
    true,
    "download errors remain actionable in the dialog",
  );
  assert.equal(
    await submit("txt").isEnabled(),
    true,
    "failed download can retry",
  );
  const retried = page.waitForEvent("download");
  await submit("txt").click();
  assert.equal(await (await retried).failure(), null);
  await closeDialog();

  await tab("script").click();
  await transcript.screenshot({ path: path.join(output, "desktop-tabs.png") });
  await openDialog("script");
  await dialog.screenshot({ path: path.join(output, "desktop-dialog.png") });
  await closeDialog();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await transcript.locator(".transcript-mode-bar").evaluate((el) => {
      window.scrollTo(0, window.scrollY + el.getBoundingClientRect().top - 180);
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
      `${width}px page fits viewport`,
    );
    await transcript.locator(".transcript-mode-bar").screenshot({
      path: path.join(output, `mobile-${width}-tabs.png`),
    });
    await openDialog("utterance");
    await formatRadio("json").check();
    await waitPreview("utterance", "json");
    const bounds = await dialog.boundingBox();
    assert.ok(
      bounds.x >= 0 && bounds.x + bounds.width <= width,
      `${width}px dialog fits viewport`,
    );
    assert.equal(
      await dialog.evaluate((el) => el.scrollWidth <= el.clientWidth),
      true,
      `${width}px dialog has no horizontal overflow`,
    );
    assert.equal(await submit("json").isVisible(), true);
    await dialog.screenshot({
      path: path.join(output, `mobile-${width}-dialog.png`),
    });
    const actionBounds = await submit("json").boundingBox();
    assert.ok(
      actionBounds.y >= bounds.y &&
        actionBounds.y + actionBounds.height <= bounds.y + bounds.height &&
        actionBounds.y >= 0 &&
        actionBounds.y + actionBounds.height <= 844,
      `${width}px download action is visible within dialog and viewport without scrolling`,
    );
    await dialog.getByRole("button", { name: "취소", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    assert.equal(
      await exportButton.evaluate((el) => el === document.activeElement),
      true,
      "Cancel restores trigger focus",
    );
  }

  assert.equal(
    downloads.length,
    9,
    "six combinations, pending download, failed download and retry",
  );
  assert.deepEqual(errors, []);
  console.log(
    "PASS: tab semantics and keyboard navigation, download badge placement, selection defaults, six export combinations and contents, preview race/error recovery, pending/error/retry downloads, Escape/Cancel focus return, 390px/320px responsive layout.",
  );
  console.log(`Screenshots: ${output}`);
} catch (error) {
  await mkdir(output, { recursive: true });
  await page?.screenshot({
    path: path.join(output, "failure.png"),
    fullPage: true,
  });
  console.error({ previews, downloads, errors });
  throw error;
} finally {
  await browser?.close();
  vite?.kill();
}
