/** Browser coverage for personal/admin history, restoration, filters and source access. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, '.runtime/rag-question-history-qa');
await mkdir(out, { recursive: true });
const base = 'http://127.0.0.1:5199';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5199', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const wid = 'a'.repeat(32), eid = 'e1';
const ws = { id: wid, name: '업무 자료', state: 'READY', document_count: 1, active_revision_id: 'r1', consent: 'provider', source: { kind: 'server', relative_path: 'docs' }, latest_job: null };
const evidence = { evidence_id: eid, workspace_id: wid, revision_id: 'r1', relative_path: '운영/정책.md', text: '운영 로그는 90일 보관합니다.', title_path: ['정책'], location: { type: 'text', start_line: 1, end_line: 1 } };
const rows = Array.from({ length: 28 }, (_, i) => ({ id: i.toString(16).padStart(32, '0'), workspace_id: wid, workspace_name: ws.name, created_at: 1789000000 - i, subject: i === 0 ? 'alice' : 'bob', account_label: i === 0 ? '앨리스' : '밥', account_role: 'visitor', kind: i === 2 ? 'search' : 'question', query: i === 0 ? '로그는 며칠 보관하나요?' : `운영 정책 질문 ${i}`, answer_preview: '운영 로그는 90일 보관합니다.', status: 'answered' }));
const result = row => ({ request_id: row.id, workspace_id: wid, revision_id: 'r1', query: row.query, created_at: row.created_at, kind: row.kind, status: row.status, answer: row.answer_preview, evidence: [evidence], citations: [eid], timings_ms: {} });
let browser;
const errors = [], checks = [];
try {
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(r => setTimeout(r, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  async function createPage(role) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    page.on('pageerror', e => errors.push(e.message));
    await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url()), p = url.pathname, scope = url.searchParams.get('scope');
      let data;
      if (p === '/api/access/session') data = { authenticated: true, role, account: { id: 'alice', label: '앨리스', role }, csrf: 'qa', limits: {} };
      else if (p === '/api/system/theme') data = { color: '#b85c12' };
      else if (p === '/api/events') data = {};
      else if (p === '/api/rag/auth/session') data = { authenticated: true, role, csrf: 'qa' };
      else if (p === '/api/rag/workspaces') data = [ws];
      else if (p === '/api/rag/diagnostics') data = { model: { state: 'READY' }, llm: { global_allowed: true, configured: true, provider_id: 'provider' }, history_days: 30, limits: {} };
      else if (p === '/api/rag/history/filters') data = { accounts: scope === 'all' ? [{ subject: 'alice', label: '앨리스', count: 1 }, { subject: 'bob', label: '밥', count: 27 }] : [], workspaces: [{ id: wid, name: ws.name }] };
      else if (p === '/api/rag/history') {
        let items = rows.filter(r => scope === 'all' || r.subject === 'alice');
        for (const key of ['subject', 'workspace_id', 'kind']) if (url.searchParams.get(key)) items = items.filter(r => r[key] === url.searchParams.get(key));
        if (url.searchParams.get('q')) items = items.filter(r => (r.query + r.answer_preview).includes(url.searchParams.get('q')));
        const offset = Number(url.searchParams.get('offset') || 0);
        data = { items: items.slice(offset, offset + 25), total: items.length, offset, limit: 25, retention_days: 30 };
      } else if (p.startsWith('/api/rag/history/')) {
        const row = rows.find(r => r.id === p.split('/').at(-1));
        data = { ...row, result: result(row) };
      } else if (p === `/api/rag/workspaces/${wid}`) data = ws;
      else if (p.endsWith('/revisions')) data = [{ id: 'r1', state: 'READY', created_at: 1789000000, manifest: {} }];
      else if (p.endsWith('/questions')) data = [result(rows[0])];
      else if (p.endsWith('/evidence/e1')) data = { workspace_id: wid, revision_id: 'r1', document: { kind: 'rendered_page', html: '<p>운영 로그는 90일 보관합니다.</p>', start_line: 1, end_line: 1, page: 0, last_page: 0, total_pages: 1, previous_page: null, next_page: null, headings: [], outline_offset: 0, outline_total: 0, anchor_found: false, continued: false, html_bytes: 64 } };
      else { errors.push(`Unexpected ${p}`); return route.fulfill({ status: 404, json: {} }); }
      await route.fulfill({ json: data });
    });
    return page;
  }
  const admin = await createPage('admin');
  await admin.goto(base + '/rag/history/all');
  await admin.getByRole('button', { name: '나중에 둘러볼게요', exact: true }).click();
  await admin.getByText('총 28건', { exact: true }).waitFor();
  await admin.screenshot({ path: path.join(out, 'admin-history-list.png'), fullPage: true });
  await admin.getByRole('button', { name: '다음', exact: true }).click();
  await admin.getByText('26–28 / 28건', { exact: true }).waitFor();
  await admin.getByLabel('계정', { exact: true }).selectOption('alice');
  await admin.getByRole('button', { name: '기록 검색', exact: true }).click();
  await admin.getByText('총 1건', { exact: true }).waitFor();
  assert.equal(await admin.locator('.query-history-row').count(), 1);
  await admin.locator('.query-history-row').click();
  await admin.getByRole('heading', { name: rows[0].query, exact: true }).waitFor();
  await admin.getByText('계정 ID: alice', { exact: true }).waitFor();
  assert.equal(new URL(admin.url()).searchParams.get('question'), rows[0].id);
  await admin.reload();
  await admin.getByRole('heading', { name: rows[0].query, exact: true }).waitFor();
  await admin.getByRole('region', { name: '저장된 출처' }).getByRole('button').waitFor();
  await admin.getByRole('region', { name: '저장된 출처' }).getByRole('button').click();
  await admin.getByRole('dialog', { name: '문서 원문' }).getByText('운영 로그는 90일 보관합니다.', { exact: true }).waitFor();
  await admin.getByRole('button', { name: '원문 닫기', exact: true }).click();
  await admin.screenshot({ path: path.join(out, 'admin-history-detail.png'), fullPage: true });
  checks.push('Admin can browse all accounts, paginate, filter by account and restore detail by ID after reload');
  await admin.getByRole('button', { name: '이 자료에서 이어 질문하기', exact: true }).click();
  assert.equal(await admin.getByLabel('검색 질문').inputValue(), rows[0].query);
  await admin.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  checks.push('Continue action restores saved question, answer and revision without calling the LLM again');
  const user = await createPage('visitor');
  await user.goto(base + '/rag/history');
  await user.getByRole('button', { name: '나중에 둘러볼게요', exact: true }).click();
  await user.getByText('총 1건', { exact: true }).waitFor();
  assert.equal(await user.getByRole('button', { name: '전체 질문 기록', exact: true }).count(), 0);
  await user.locator('.query-history-row').click();
  await user.reload();
  await user.getByRole('heading', { name: rows[0].query, exact: true }).waitFor();
  await user.setViewportSize({ width: 390, height: 844 });
  await user.screenshot({ path: path.join(out, 'personal-history-mobile.png'), fullPage: true });
  assert.equal(await user.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await user.getByRole('button', { name: '기록 목록', exact: true }).click();
  await user.getByLabel('질문·답변 검색').fill('없는 질문');
  await user.getByRole('button', { name: '기록 검색', exact: true }).click();
  await user.getByText('조건에 맞는 질문 기록이 없습니다.', { exact: true }).waitFor();
  await user.screenshot({ path: path.join(out, 'personal-history-filter-mobile.png'), fullPage: true });
  assert.equal(await user.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await user.goto(base + '/rag/history/all');
  await user.getByText('전체 질문 기록은 관리자만 확인할 수 있습니다.', { exact: true }).waitFor();
  checks.push('Visitor sees only personal history, empty filtered state, mobile layout and admin route denial');
  assert.deepEqual(errors, []);
  await writeFile(path.join(out, 'report.json'), JSON.stringify({ checks, errors }, null, 2));
  console.log(JSON.stringify({ checks, errors, out }, null, 2));
} finally { await browser?.close(); server.kill(); }
