/** Synthetic STT script/player checks; all API requests are intercepted. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { chromium } from "../frontend/node_modules/playwright-core/index.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const base = process.env.STT_UI_BASE || "http://127.0.0.1:5177";
const output = path.join(root, ".runtime/stt-script-qa");
const vite = process.env.STT_UI_BASE
  ? null
  : spawn(
      process.execPath,
      [
        path.join(root, "frontend/node_modules/vite/bin/vite.js"),
        "--host",
        "127.0.0.1",
        "--port",
        "5177",
        "--strictPort",
      ],
      { cwd: path.join(root, "frontend"), stdio: "ignore" },
    );
let browser;
let page;
try {
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
  page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    hasTouch: true,
  });
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(String(error)));
  await page.addInitScript(() =>
    sessionStorage.setItem("stt-token", "synthetic"),
  );
  const u = (id, start, end, speaker, text) => ({
    utterance_id: id,
    revision: 1,
    start_ms: start,
    end_ms: end,
    speaker_id: speaker,
    text,
    status: "stable",
    speaker_status: "assigned",
    overlap: false,
    manual_fields: [],
  });
  let state = "DIARIZING";
  const utterances = [
    u("first", 120100, 129900, "A", "첫 번째 발언입니다."),
    u("second", 131000, 140000, "A", "이렇게 해주면"),
    u("unknown", 140000, 141500, null, "될"),
    u("fourth", 141500, 146000, "A", "것 같아요. 알겠습니다."),
    ...Array.from({ length: 24 }, (_, i) =>
      u(
        `later-${i}`,
        147000 + i * 5000,
        152000 + i * 5000,
        i % 2 ? "A" : "B",
        `대본 ${i + 2}. 다음 내용을 이야기합니다. `.repeat(4),
      ),
    ),
  ];
  utterances[1].words = [
    { text: " 이렇게", start_ms: 131000, end_ms: 131200 },
    { text: " 해주면", start_ms: 132000, end_ms: 140000 },
  ];
  utterances.at(-1).text = "긴 대본의 다음 단어를 확인합니다. "
    .repeat(100)
    .trim();
  const snapshot = () => ({
    id: "synthetic-script",
    snapshot_revision: state === "DIARIZING" ? 1 : 2,
    mode: "file",
    state,
    utterances,
    speakers: { A: "화자 A", B: "화자 B" },
    warnings: [],
    metrics: {},
    audio_retained: false,
  });
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
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
                id: "synthetic-script",
                mode: "file",
                state,
                created_at: 1770000000,
              },
            ]
          : pathname === "/api/stt/sessions/synthetic-script"
            ? snapshot()
            : undefined;
    if (data === undefined) {
      errors.push(`Unexpected API: ${pathname}`);
      await route.abort();
    } else await route.fulfill({ json: data });
  });
  await page.goto(base);
  await page.locator(".history button").click();
  assert.equal(
    await page
      .getByRole("tab", { name: "대본 보기", exact: true })
      .isDisabled(),
    true,
  );
  state = "COMPLETED";
  await page.waitForFunction(
    () =>
      ![...document.querySelectorAll("button")].find(
        (b) => b.textContent === "대본 보기",
      )?.disabled,
  );
  assert.equal(
    await page.locator(".script-block").count(),
    0,
    "conversion must be explicit",
  );
  await page.getByRole("tab", { name: "대본 보기", exact: true }).click();
  assert.equal(await page.locator(".script-block").count(), 25);
  assert.match(
    await page.locator(".script-block").first().innerText(),
    /02:00\.1 ~ 02:26\.0/,
  );
  assert.match(
    await page.locator(".script-block").first().innerText(),
    /이렇게 해주면 될 것 같아요/,
  );
  assert.equal(await page.locator(".script-block").first().isDisabled(), true);
  assert.equal(
    await page.locator(".transcript-word").count(),
    0,
    "no word controls without local audio",
  );

  const samples = 8000 * 280;
  const wav = Buffer.alloc(44 + samples * 2);
  wav.write("RIFF");
  wav.writeUInt32LE(wav.length - 8, 4);
  wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24);
  wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write("data", 36);
  wav.writeUInt32LE(samples * 2, 40);
  await page.locator(".local-player input[type=file]").setInputFiles({
    name: "synthetic.wav",
    mimeType: "audio/wav",
    buffer: wav,
  });
  await page.waitForFunction(
    () => document.querySelector("audio")?.readyState >= 1,
  );
  await page.locator(".script-block").first().click();
  await page.waitForFunction(() => {
    const a = document.querySelector("audio");
    return !a.paused && a.currentTime >= 120.1 && a.currentTime < 122;
  });
  assert.match(
    await page.locator(".selected-utterance").innerText(),
    /02:00\.1 – 02:26\.0/,
  );
  await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  assert.equal(
    await page
      .getByRole("radio", { name: "싱크 끄기", exact: true })
      .isChecked(),
    true,
  );
  const seek = (seconds) =>
    page.locator("audio").evaluate((audio, seconds) => {
      audio.currentTime = seconds;
      audio.dispatchEvent(new Event("timeupdate"));
    }, seconds);
  await page.locator(".utterances").evaluate((list) => (list.scrollTop = 0));
  await seek(240);
  await page.waitForFunction(
    () =>
      document
        .querySelector(".script-block.playing")
        ?.getAttribute("data-range-id") === "later-18",
  );
  assert.equal(
    await page.locator(".utterances").evaluate((list) => list.scrollTop),
    0,
    "sync off preserves scroll",
  );
  await page.getByRole("radio", { name: "싱크 켜기", exact: true }).check();
  await page.waitForFunction(
    () => document.querySelector(".utterances").scrollTop > 1000,
  );
  const scrollBefore = await page
    .locator(".utterances")
    .evaluate((list) => list.scrollTop);
  await page.getByRole("button", { name: "음성 재생", exact: true }).click();
  await seek(257.5);
  await page.waitForFunction(
    () =>
      document
        .querySelector(".script-block.playing")
        ?.getAttribute("data-range-id") === "later-22",
  );
  assert.ok(
    (await page.locator(".utterances").evaluate((list) => list.scrollTop)) >
      scrollBefore,
  );
  await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  await seek(120.1);
  await page.waitForFunction(
    () => document.querySelector(".utterances").scrollTop === 0,
  );
  await page.getByRole("tab", { name: "발화별 보기", exact: true }).click();
  assert.equal(await page.locator(".utterance").count(), 28);
  assert.match(
    await page.locator('[data-range-id="unknown"]').innerText(),
    /화자 미확정/,
  );
  await seek(240);
  await page.waitForFunction(
    () => document.querySelector(".utterances").scrollTop > 1000,
  );
  await page.getByRole("tab", { name: "대본 보기", exact: true }).click();
  const highlight = page.getByRole("checkbox", {
    name: "현재 단어 강조",
    exact: true,
  });
  assert.equal(await highlight.isChecked(), false);
  assert.equal(await page.locator(".transcript-word").count(), 0);
  await highlight.check();
  const firstBlock = page.locator(".script-block").first();
  const textBeforeWordSeek = await firstBlock
    .locator(".script-text")
    .textContent();
  const playWord = async (word, seconds, action = "click") => {
    if (action === "Enter" || action === "Space") await word.press(action);
    else if (action === "tap") await word.tap();
    else await word.click();
    await page.waitForFunction((seconds) => {
      const audio = document.querySelector("audio");
      return (
        !audio.paused &&
        audio.currentTime >= seconds &&
        audio.currentTime < seconds + 0.8
      );
    }, seconds);
    await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  };
  await playWord(firstBlock.getByRole("button", { name: /^해주면 ·/ }), 132);
  assert.match(
    await page.locator(".selected-utterance").innerText(),
    /02:12\.0 – 02:20\.0/,
  );
  assert.equal(
    await firstBlock.locator(".script-text").textContent(),
    textBeforeWordSeek,
  );
  assert.equal(
    await page.locator("button button").count(),
    0,
    "word playback buttons must not be nested",
  );
  await firstBlock.getByRole("button", { name: /^해주면 ·/ }).click();
  await page.waitForFunction(() => !document.querySelector("audio").paused);
  await firstBlock.getByRole("button", { name: /^될 ·/ }).click();
  await page.waitForFunction(() => {
    const audio = document.querySelector("audio");
    return (
      !audio.paused && audio.currentTime >= 140 && audio.currentTime < 140.8
    );
  });
  await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  await seek(136);
  await playWord(
    firstBlock.getByRole("button", { name: /^해주면 ·/ }),
    132,
    "Enter",
  );
  await playWord(
    firstBlock.getByRole("button", { name: /^될 ·/ }),
    140,
    "Space",
  );
  await playWord(
    firstBlock.getByRole("button", { name: /^발언입니다\. ·/ }),
    123.366666,
  );
  await firstBlock.getByTitle("대본 처음부터 재생").click();
  await page.waitForFunction(() => {
    const audio = document.querySelector("audio");
    return (
      !audio.paused && audio.currentTime >= 120.1 && audio.currentTime < 121
    );
  });
  await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  await seek(131.1);
  await page.waitForFunction(
    () => document.querySelector(".current-word")?.textContent === "이렇게",
  );
  assert.equal(await page.locator(".current-word").count(), 1);
  const originalText = await page.locator(".script-text").first().textContent();
  await seek(131.5);
  await page.waitForFunction(() => !document.querySelector(".current-word"));
  await seek(132.1);
  await page.waitForFunction(
    () => document.querySelector(".current-word")?.textContent === "해주면",
  );
  assert.equal(
    await page.locator(".script-text").first().textContent(),
    originalText,
  );
  await seek(130);
  await page.waitForFunction(() => !document.querySelector(".current-word"));
  await seek(120.1);
  await page.waitForFunction(
    () => document.querySelector(".current-word")?.textContent === "첫",
  );
  await highlight.uncheck();
  assert.equal(await page.locator(".current-word").count(), 0);
  assert.equal(await page.locator(".transcript-word").count(), 0);
  await highlight.check();
  await page.getByRole("radio", { name: "싱크 끄기", exact: true }).check();
  assert.equal(await highlight.isDisabled(), true);
  assert.equal(await highlight.isChecked(), true);
  assert.equal(await page.locator(".current-word").count(), 0);
  assert.equal(
    await page.locator(".transcript-word").count(),
    0,
    "sync off also disables word seeking",
  );
  await page.getByRole("radio", { name: "싱크 켜기", exact: true }).check();
  await seek(132.1);
  await page.getByRole("tab", { name: "발화별 보기", exact: true }).click();
  await page.waitForFunction(
    () =>
      document.querySelector(".utterance .current-word")?.textContent ===
      "해주면",
  );
  await seek(130);
  await playWord(
    page
      .locator('[data-range-id="second"]')
      .getByRole("button", { name: /^해주면 ·/ }),
    132,
  );
  await page.locator('[data-range-id="second"] .edit-button').click();
  assert.equal(
    await page.getByRole("textbox", { name: "발언 수정" }).inputValue(),
    "이렇게 해주면",
  );
  assert.equal(await page.locator(".current-word").count(), 0);
  await page.getByRole("button", { name: "취소", exact: true }).click();
  await page.getByRole("tab", { name: "대본 보기", exact: true }).click();
  await seek(262);
  await page.waitForFunction(() => {
    const block = document.querySelector(
      '.script-block.playing[data-range-id="later-23"]',
    );
    const word = block?.querySelector(".current-word");
    const list = document.querySelector(".utterances").getBoundingClientRect();
    const bounds = word?.getBoundingClientRect();
    return (
      word?.textContent === "긴" &&
      bounds.top >= list.top &&
      bounds.bottom <= list.bottom
    );
  });
  const longBlockScroll = await page
    .locator(".utterances")
    .evaluate((list) => list.scrollTop);
  await seek(266.999);
  await page.waitForFunction(() => {
    const list = document.querySelector(".utterances").getBoundingClientRect();
    const mark = document.querySelector(".current-word");
    const word = mark?.getBoundingClientRect();
    return (
      mark?.textContent === "확인합니다." &&
      word.top >= list.top &&
      word.bottom <= list.bottom
    );
  });
  assert.ok(
    (await page.locator(".utterances").evaluate((list) => list.scrollTop)) >
      longBlockScroll,
  );
  await seek(267);
  await page.waitForFunction(() => !document.querySelector(".current-word"));
  await page
    .getByRole("combobox", { name: "재생 속도", exact: true })
    .selectOption("2");
  await seek(131.7);
  await page.getByRole("button", { name: "음성 재생", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelector(".current-word")?.textContent === "해주면",
  );
  await page.getByRole("button", { name: "일시 정지", exact: true }).click();
  const pausedWord = await page.locator(".current-word").textContent();
  await page.waitForTimeout(150);
  assert.equal(await page.locator(".current-word").textContent(), pausedWord);
  await seek(120.1);
  await page.locator(".transcript").scrollIntoViewIfNeeded();
  await mkdir(output, { recursive: true });
  await page.screenshot({
    path: path.join(output, "desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await playWord(
    page
      .locator(".script-block")
      .first()
      .getByRole("button", { name: /^해주면 ·/ }),
    132,
    "tap",
  );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
    "mobile fits viewport",
  );
  await page
    .locator(".transcript")
    .screenshot({ path: path.join(output, "mobile.png") });
  assert.deepEqual(errors, []);
  console.log(
    "PASS: explicit conversion, grouping, original preservation, playback, sync/word options, exact/estimated word seeks, keyboard Enter/Space, mobile tap, block-start playback, silence, reverse seeks, editing, long-block following, 2x playback, pause and responsive layout.",
  );
  console.log(`Screenshots: ${output}`);
} catch (error) {
  await mkdir(output, { recursive: true });
  await page?.screenshot({
    path: path.join(output, "failure.png"),
    fullPage: true,
  });
  console.error(
    await page?.evaluate(() => ({
      playbackTime: document.querySelector("audio")?.currentTime,
      activeWord: document.querySelector(".current-word")?.textContent,
      activeRange: document
        .querySelector(".script-block.playing")
        ?.getAttribute("data-range-id"),
      scroll: document.querySelector(".utterances")?.scrollTop,
    })),
  );
  throw error;
} finally {
  await browser?.close();
  vite?.kill();
}
