/** Browser integration checks with synthetic API fixtures; never calls live STT/RAG APIs. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const base = 'http://127.0.0.1:5174';
const output = path.join(root, '.runtime/meeting-ui-qa');
const reportPath = path.join(root, 'docs/meeting/ui-test-results.json');
const report = { synthetic: true, checks: [], errors: [], unexpectedRequests: [], screenshots: output };
await mkdir(output, { recursive: true });
await mkdir(path.dirname(reportPath), { recursive: true });

let vite;
try {
  await fetch(base, { signal: AbortSignal.timeout(1000) });
} catch {
  vite = spawn(process.execPath, [path.join(root, 'frontend/node_modules/vite/bin/vite.js'), '--host', '127.0.0.1', '--port', '5174', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try { await fetch(base, { signal: AbortSignal.timeout(1000) }); break; }
    catch { if (attempt === 29) throw new Error('Vite did not start'); await new Promise((resolve) => setTimeout(resolve, 200)); }
  }
}

const widA = 'a'.repeat(32), widB = 'b'.repeat(32), ridA = 'c'.repeat(32), ridB = 'd'.repeat(32);
const fixtureText = [
  '운영서버 로그 기록은 45일 남아요.',
  '운영서버 접속할 때는 개인키가 필요해요.',
  '배포 후에는 모니터링 대시보드를 확인할게요.',
  '개발서버 로그는 30일 보관합니다.',
];
const titles = ['운영 로그 보관 기간 정정', '개인키 발급 절차', '배포 후 확인할 대시보드', '개발 로그 보관 기간 일치'];
const messages = [
  '운영서버 로그는 90일 보관합니다. 개발서버 로그는 30일 보관합니다.',
  '개인키 신청 방법은 접속 가이드에서 확인할 수 있습니다. 발급은 인프라 담당자에게 요청하세요.',
  '배포 후 서비스 상태는 운영 모니터링 대시보드에서 확인할 수 있습니다.',
  '개발서버 로그 30일 보관은 현재 문서와 일치합니다.',
];
const kinds = ['warning', 'caution', 'info', 'success'];
const colors = ['red', 'orange', 'blue', 'green'];
let session = {
  id: 'session_synthetic_meeting_ui', snapshot_revision: 1, mode: 'microphone', state: 'COMPLETED',
  created_at: 1770000000, speakers: { speaker_a: '김민수', speaker_b: '박지은' },
  warnings: [], metrics: { audio_input_ms: 9000 }, audio_retained: false,
  options: { model: 'small', language: 'ko', num_speakers: null, retain_audio: false },
  utterances: fixtureText.map((text, index) => ({
    utterance_id: `utt_synthetic_${index}`, revision: 1, text, start_ms: index * 2000,
    end_ms: index * 2000 + 1000, status: 'stable', speaker_id: index % 2 ? 'speaker_b' : 'speaker_a',
    speaker_status: 'assigned', overlap: false, manual_fields: [],
  })),
};
const workspaces = [
  { id: widA, name: '검증용 운영 문서', active_revision_id: ridA },
  { id: widB, name: '검증용 개발 문서', active_revision_id: ridB },
].map((item) => ({ ...item, description: '', state: 'READY', document_count: 2, consent: 'fixture-provider', access_state: 'AVAILABLE', source: null, latest_job: null }));
const diagnostics = {
  model: { state: 'READY', model: 'SYNTHETIC_EMBEDDING', revision: 'fixture', device: 'fake', dimension: 384 },
  llm: { global_allowed: true, configured: true, provider_id: 'fixture-provider', endpoint: 'http://127.0.0.1', model: '검증용 AI 응답', scope: 'synthetic' },
  access_mode: 'local', history_days: 30, versions: 'fixture', limits: {},
};
const health = {
  engine: 'fake', active_session: null,
  limits: { file_mb: 4096, file_seconds: 18000, live_seconds: 300 },
  workers: { asr: { ready: true }, diar: { ready: true }, vad: { ready: true } },
  environment: { machine: '브라우저 검증', system: 'synthetic' },
};
let delayedReady;
const delayedStarted = new Promise((resolve) => { delayedReady = resolve; });
let delayedRelease;
const delayResponse = new Promise((resolve) => { delayedRelease = resolve; });
let analyzed = 0;

function result(wid, body) {
  const u = body.utterance;
  const index = Number(u.utterance_id.at(-1)) || 0;
  const corrected = u.text.includes('정정한 운영 로그');
  const i = corrected ? 3 : Math.min(index, 3);
  const rid = wid === widA ? ridA : ridB;
  const eid = `${rid}.${String(index + 1).padStart(32, '0')}`;
  const text = messages[i];
  return {
    workspace_id: wid, session_id: body.session_id, utterance_id: u.utterance_id,
    utterance_revision: u.revision, revision_id: rid, request_id: 'synthetic_request', status: 'popup',
    analysis: { keywords: i === 1 ? ['운영서버', '개인키', '발급 절차'] : ['로그 기록', '보관 기간'], query: u.text, intent: i === 1 ? 'practical_guidance' : 'fact_check', claim: u.text },
    popup: { id: `${wid}-${u.utterance_id}`, kind: kinds[i], color: colors[i], title: corrected ? '수정된 운영 로그 발화 확인' : titles[i], message: text, confidence: 0.95, citations: [eid] },
    evidence: [{ evidence_id: eid, workspace_id: wid, revision_id: rid, relative_path: '검증용/서버-운영-정책.md', text, title_path: ['서버 운영 정책'], location: { type: 'text', start_line: 3, end_line: 5 } }],
    timings_ms: { extraction: 80, retrieval: 50, generation: 100, total: 230 },
  };
}

const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await context.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic-browser-key'));
  const page = await context.newPage();
  page.on('pageerror', (error) => report.errors.push(error.message));
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const send = (data, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) }).catch(() => {});
    if (url.origin !== base) { report.unexpectedRequests.push(request.url()); return send({ detail: 'FIXTURE_ONLY' }, 500); }
    if (url.pathname === '/api/stt/health') return send(health);
    if (url.pathname === '/api/stt/sessions') return send([session]);
    if (url.pathname === `/api/stt/sessions/${session.id}`) return send(session);
    if (url.pathname === '/api/stt/meeting/config') return send({ rag_url: 'https://docs.example.test/rag' });
    if (url.pathname === '/api/stt/meeting/workspaces') return send(workspaces);
    if (url.pathname === '/api/stt/meeting/diagnostics') return send(diagnostics);
    const match = url.pathname.match(/^\/api\/stt\/meeting\/workspaces\/([a-f0-9]{32})\/analyze$/);
    if (match) {
      analyzed += 1;
      const body = request.postDataJSON();
      if (body.utterance.utterance_id === 'utt_delayed' && match[1] === widA) { delayedReady(); await delayResponse; }
      return send(result(match[1], body));
    }
    report.unexpectedRequests.push(request.url());
    return send({ detail: 'UNEXPECTED_SYNTHETIC_ROUTE' }, 500);
  });

  await page.goto(base);
  await page.getByRole('button', { name: /실시간.*(?:전사|회의)/ }).click();
  await page.getByRole('button', { name: /마이크 녹음/ }).click();
  const enable = page.getByRole('button', { name: /^(?:어시스턴트|도우미) 켜기$/ });
  await enable.waitFor();
  await page.waitForFunction(() => document.querySelector('.meeting-toggle')?.disabled === false);
  await enable.click();
  for (const color of colors) await page.locator(`.meeting-popup.meeting-${color}`).waitFor({ timeout: 15000 });
  assert.equal(await page.locator('.meeting-popup').count(), 4);
  assert.equal(analyzed, 4, 'Each stable utterance is analyzed once');
  await page.locator('.meeting-popup.meeting-red summary').click();
  await page.locator('.meeting-popup.meeting-red .meeting-source').waitFor();
  report.checks.push('Four LLM-selected popup concepts, source quotations, speakers and keyword tags render');
  await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('.meeting-assistant').scrollTop = 0; });
  await page.screenshot({ path: path.join(output, 'meeting-desktop.png'), fullPage: true });
  for (const color of colors) await page.locator(`.meeting-popup.meeting-${color}`).screenshot({ path: path.join(output, `popup-${color}.png`) });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector('.meeting-popups').scrollTop = 0; });
  await page.screenshot({ path: path.join(output, 'meeting-mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false, 'Mobile horizontal overflow');
  report.checks.push('Desktop and 390px mobile screenshots; no horizontal overflow');
  await page.setViewportSize({ width: 1440, height: 1100 });

  await page.getByRole('button', { name: `${titles[2]} 안내 닫기`, exact: true }).click();
  await page.waitForTimeout(1300);
  assert.equal(await page.locator('.meeting-popup.meeting-blue').count(), 0);
  assert.equal(analyzed, 4, 'Polling must not repeat dismissed stable utterances');
  report.checks.push('Dismissed card remains dismissed across session polling');

  session.utterances[0] = { ...session.utterances[0], revision: 2, status: 'corrected', text: '정정한 운영 로그 보관 기간은 90일입니다.' };
  session.snapshot_revision += 1;
  await page.locator('.meeting-popup.meeting-red').waitFor({ state: 'detached' });
  await page.getByRole('heading', { name: '수정된 운영 로그 발화 확인', exact: true }).waitFor();
  assert.equal(analyzed, 5);
  report.checks.push('Edited utterance removes previous red assertion and replaces it with the current result');

  session.utterances.push({ ...session.utterances[0], utterance_id: 'utt_delayed', revision: 1, start_ms: 10000, end_ms: 11000, text: '운영 정책의 지연 응답 검증', status: 'stable' });
  session.snapshot_revision += 1;
  await Promise.race([delayedStarted, new Promise((_, reject) => setTimeout(() => reject(new Error('Delayed request did not start')), 10000))]);
  await page.getByLabel('참조할 지식 워크스페이스', { exact: true }).selectOption(widB);
  delayedRelease();
  await page.waitForTimeout(700);
  assert.equal(await page.locator('.meeting-popup').count(), 0);
  assert.equal(await page.getByRole('button', { name: /^(?:어시스턴트|도우미) 켜기$/ }).isVisible(), true);
  report.checks.push('Workspace switch aborts old scope; late A response cannot populate B');

  workspaces[1].consent = null;
  await page.getByRole('button', { name: 'RAG 연결 상태 새로고침', exact: true }).click();
  await page.getByText('RAG에서 이 워크스페이스의 외부 AI 전송을 승인해 주세요.', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: /^(?:어시스턴트|도우미) 켜기$/ }).isDisabled(), true);
  const beforeBlocked = analyzed;
  await page.waitForTimeout(1300);
  assert.equal(analyzed, beforeBlocked);
  report.checks.push('Missing workspace consent disables analysis without sending an utterance');
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.unexpectedRequests, []);
  report.checks.push('No runtime errors; every API request intercepted by synthetic same-origin fixtures');
  await context.close();
} finally {
  delayedRelease();
  await browser.close();
  vite?.kill();
  await writeFile(reportPath, JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
