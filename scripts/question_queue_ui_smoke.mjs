/** Async question UX with synthetic API responses; never calls an external model. */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime/question-queue-qa');
await mkdir(output, { recursive: true });
const base = 'http://127.0.0.1:5198';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5198', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const wid = 'a'.repeat(32), revision = 'b'.repeat(32);
const ws = { id: wid, name: '큐 검증 자료', state: 'READY', document_count: 1, active_revision_id: revision, consent: 'provider', source: { kind: 'server', relative_path: 'docs' }, latest_job: null };
const jobs = [], keys = [], errors = [], checks = [];
let browser, transientFailures = 0;
const detail = (job) => ({ id: job.request_id, workspace_id: wid, workspace_name: ws.name, subject: 'alice', account_label: '사용자', account_role: 'visitor', created_at: job.created_at, kind: 'question', result: job });
try {
  for (let i = 0; i < 60; i++) {
    try { await fetch(base); break; } catch { await new Promise(resolve => setTimeout(resolve, 100)); }
  }
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(12000);
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  await page.route('**/api/**', async route => {
    const request = route.request(), p = new URL(request.url()).pathname;
    let data, status = 200;
    if (p === '/api/access/session') data = { authenticated: true, role: 'visitor', account: { id: 'alice', label: '사용자', role: 'visitor' }, csrf: 'qa', limits: {} };
    else if (p === '/api/system/theme') data = { color: '#b85c12' };
    else if (p === '/api/events') data = {};
    else if (p === '/api/rag/auth/session') data = { authenticated: true, role: 'visitor', csrf: 'qa' };
    else if (p === '/api/rag/workspaces') data = [ws];
    else if (p === '/api/rag/diagnostics') data = { model: { state: 'READY' }, llm: { global_allowed: true, configured: true, provider_id: 'provider' }, history_days: 30, limits: {} };
    else if (p === `/api/rag/workspaces/${wid}`) data = ws;
    else if (p.endsWith('/revisions')) data = [{ id: revision, state: 'READY', created_at: Date.now() / 1000, manifest: {} }];
    else if (p.endsWith('/questions')) {
      if (request.method() === 'POST') {
        const key = request.headers()['idempotency-key'];
        assert(key, 'Submission must carry an idempotency key');
        keys.push(key);
        data = { request_id: (jobs.length + 1).toString(16).padStart(32, '0'), workspace_id: wid, revision_id: revision,
          query: request.postDataJSON().query, status: 'queued', answer: '', evidence: [], citations: [], timings_ms: {}, kind: 'question', created_at: Date.now() / 1000 };
        jobs.unshift(data);
        status = 202;
      } else data = jobs;
    } else if (p === '/api/rag/history/filters') data = { accounts: [], workspaces: [{ id: wid, name: ws.name }] };
    else if (p === '/api/rag/history') data = { items: jobs.map(j => ({ ...detail(j), query: j.query, status: j.status, answer_preview: j.answer })), total: jobs.length, offset: 0, limit: 25, retention_days: 30 };
    else if (p.startsWith('/api/rag/history/')) {
      if (transientFailures > 0) {
        transientFailures--;
        return route.fulfill({ status: 503, json: { error_code: 'RAG_UNAVAILABLE' } });
      }
      const job = jobs.find(j => j.request_id === p.split('/').at(-1));
      assert(job, 'Unknown question ID');
      data = detail(job);
    } else {
      errors.push(`Unexpected ${request.method()} ${p}`);
      return route.fulfill({ status: 404, json: {} });
    }
    await route.fulfill({ status, json: data }).catch(() => {});
  });

  await page.goto(base + '/rag');
  await page.getByRole('button', { name: '나중에 둘러볼게요', exact: true }).click();
  await page.locator('.rag-space-card').filter({ hasText: ws.name }).click();
  await page.getByLabel('검색 질문').fill('첫 번째 질문');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await page.getByRole('heading', { name: '질문이 접수되었습니다 · 처리 대기 중', exact: true }).waitFor();
  assert(await page.getByRole('button', { name: '질문하기', exact: true }).isEnabled());
  assert.equal(await page.getByText('선택한 자료에서 확인할 수 없습니다.', { exact: true }).count(), 0);
  await page.getByLabel('검색 질문').fill('두 번째 질문');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await page.getByRole('status').getByText('두 번째 질문', { exact: true }).waitFor();
  assert.equal(jobs.length, 2);
  assert.notEqual(keys[0], keys[1]);
  checks.push('Immediate acceptance leaves the form usable for another question; queued results do not show empty-evidence errors');

  await page.reload();
  await page.getByRole('status').getByText('두 번째 질문', { exact: true }).waitFor();
  assert.equal(jobs.length, 2, 'Reload must never resubmit the question');
  await page.screenshot({ path: path.join(output, 'queued-desktop.png'), fullPage: true });
  jobs[0].status = 'processing';
  await page.getByRole('heading', { name: '자료 확인 · 답변 생성 중', exact: true }).waitFor();
  transientFailures = 1;
  jobs[0].status = 'answered';
  jobs[0].answer = '두 번째 질문의 저장된 답변입니다.';
  await page.getByText(jobs[0].answer, { exact: true }).waitFor();
  assert.equal(jobs.length, 2);
  checks.push('Reload restores the original request; polling recovers from a transient error and renders the completed result without resubmission');

  await page.getByRole('button', { name: '내 질문 기록 전체 보기' }).click();
  await page.locator('.query-history-row').filter({ hasText: '첫 번째 질문' }).click();
  await page.getByRole('heading', { name: '질문이 접수되었습니다 · 처리 대기 중', exact: true }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'queued-history-mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  jobs[1].status = 'processing';
  await page.getByRole('heading', { name: '자료 확인 · 답변 생성 중', exact: true }).waitFor();
  jobs[1].status = 'answered';
  jobs[1].answer = '첫 번째 질문도 처리가 완료되었습니다.';
  await page.getByText(jobs[1].answer, { exact: true }).waitFor();
  await page.reload();
  await page.getByText(jobs[1].answer, { exact: true }).waitFor();
  checks.push('Navigating away preserves both requests; history polls queued/processing states, restores results on reload, and fits mobile width');
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'results.json'), JSON.stringify({ synthetic: true, checks, errors, submitted: jobs.length }, null, 2));
  console.log(JSON.stringify({ checks, errors, submitted: jobs.length }, null, 2));
} finally {
  if (browser) await browser.close();
  server.kill('SIGTERM');
}
