/** Server-rendered bounded-page regression checks. No real documents or AI calls. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import { markdownFixtures } from './markdown_fixture_client.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime/markdown-integrity-qa');
await mkdir(output, { recursive: true });
const base = 'http://127.0.0.1:5198';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5198', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const report = { synthetic: true, checks: [], errors: [] };
const renderer = markdownFixtures(root);
const lines = [
  '# 구조 검증', '', '## 목차', '',
  '1. [첫 제목](#같은-제목)',
  '   - [두 번째 제목](#같은-제목-1)',
  '   - [연결 문서](가이드.md#세부_항목)',
  '2. [표](#표)', '',
  '## 같은 제목', '', '**첫 문단 시작', '문단 끝**', '',
  '## 같은 제목', '', '두 번째 내용', '',
  '## 표', '', '| 항목 | 기간 |', '| --- | --- |', '| 자료 | **73일** |', '| 회의 | 90일 |', '',
  '## 코드', '', '````js', 'const marker = "보존";', '# 코드 내부 제목', '```', '````', '',
  '## 참조', '', '참조 [정의 링크][reference]와 각주[^가].', '',
  ...Array.from({ length: 200 }, (_, index) => `- 긴 목록 ${index + 1}`), '',
  '[reference]: https://example.com/reference', '', '[^가]: **각주 원문**',
];
const source = lines.join('\n');
const linked = '# 연결 문서\n\n#### 세부_항목\n\n연결된 항목 본문입니다.';
const lineOf = (value) => lines.indexOf(value) + 1;
const ws = { id: 'integrity', name: '문서 구조 검증', state: 'READY', document_count: 2, active_revision_id: 'revision-integrity', consent: 'qa', source: { root_id: 'qa', relative_path: '' }, latest_job: null };
let start = 6, end = 6, failSnapshot = false, wrongScope = false, delaySnapshot = false, requestCount = 0;
const delayedSnapshots = [];
let browser;
try {
  await renderer.add('main', source);
  await renderer.add('linked', linked);
  await renderer.add('stale', '# STALE_DOCUMENT');
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(resolve => setTimeout(resolve, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => report.errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  const evidence = (id = 'source') => ({ workspace_id: ws.id, revision_id: ws.active_revision_id, evidence_id: id, relative_path: id === 'linked' ? '가이드.md' : '목차.md', text: 'BROKEN_FRAGMENT](#잘림', title_path: ['목차'], location: { type: 'text', start_line: start, end_line: end } });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace('/api/rag', '');
    let data;
    if (url.pathname === '/api/access/session') data = { authenticated: true, role: 'superadmin', demo: false, csrf: 'qa', limits: {} };
    else if (p === '/auth/session') data = { csrf: 'qa' };
    else if (p === '/workspaces') data = [ws];
    else if (p === `/workspaces/${ws.id}`) data = ws;
    else if (p === '/diagnostics') data = { model: { state: 'READY' }, llm: { global_allowed: true, provider_id: 'qa', configured: true }, limits: {} };
    else if (p.endsWith('/revisions') || p.endsWith('/questions')) data = [];
    else if (p.endsWith('/search')) data = { workspace_id: ws.id, revision_id: ws.active_revision_id, request_id: `request-${++requestCount}`, query: '', status: 'found', evidence: [evidence(`source-${requestCount}`)], timings_ms: {} };
    else if (p.endsWith('/documents')) {
      assert.equal(url.searchParams.get('relative_path'), '가이드.md');
      data = { evidence: evidence('linked') };
    } else if (p.includes('/evidence/')) {
      if (failSnapshot) return route.fulfill({ status: 503, json: { message: 'Synthetic failure' } });
      const delayed = delaySnapshot;
      assert.ok(url.searchParams.has('view'), 'Viewer must never request a complete snapshot');
      const doc = await renderer.render(delayed ? 'stale' : p.endsWith('/linked') ? 'linked' : 'main', p.endsWith('/linked') ? { ...evidence(), location: { start_line: 1, end_line: 1 } } : evidence(), url.searchParams);
      data = { workspace_id: wrongScope ? 'another-workspace' : ws.id, revision_id: ws.active_revision_id, document: doc };
      if (delayed) await new Promise(resolve => { delayedSnapshots.push(resolve); });
    } else { report.errors.push(`Unexpected ${p}`); return route.fulfill({ status: 404, json: {} }); }
    await route.fulfill({ json: data }).catch(() => {});
  });
  await page.goto(base + '/rag');
  await page.locator('.rag-spaces button').filter({ hasText: ws.name }).click();
  const card = page.locator('.rag-evidence-card');
  const md = card.locator('.rag-markdown');
  async function search(from, to = from) {
    start = from; end = to;
    await page.getByLabel('검색 질문', { exact: true }).fill(`검증 ${requestCount + 1}`);
    await page.getByRole('button', { name: '문서 검색', exact: true }).click();
  }
  await search(6);
  await md.locator('ol').waitFor();
  assert.equal(await md.locator('li').count(), 4);
  assert.ok(!await md.textContent().then(text => text.includes('BROKEN_FRAGMENT')));
  await md.getByRole('link', { name: '두 번째 제목', exact: true }).click();
  await page.locator('.rag-drawer [data-document-anchor="같은-제목-1"]').waitFor();
  await page.waitForFunction(() => document.activeElement?.getAttribute('data-document-anchor') === '같은-제목-1');
  assert.equal(await page.getByRole('navigation', { name: '문서 목차' }).locator('button').count(), 7);
  await page.keyboard.press('Escape');
  await md.getByRole('link', { name: '연결 문서', exact: true }).click();
  await page.waitForFunction(() => document.activeElement?.getAttribute('data-document-anchor') === '세부_항목');
  assert.equal(await page.locator('.rag-drawer .rag-markdown h4').textContent(), '세부_항목');
  await page.keyboard.press('Escape');
  report.checks.push('Cut nested TOC reconstructs complete list; missing preview anchors open full document; duplicate heading and relative document#fragment navigation work');

  await search(lineOf('| 자료 | **73일** |'));
  await md.locator('table').waitFor();
  assert.equal(await md.locator('th').count(), 2);
  assert.equal(await md.locator('tbody tr').count(), 2);
  assert.equal(await md.locator('strong').textContent(), '73일');
  await page.screenshot({ path: path.join(output, 'expanded-table-desktop.png'), fullPage: true });
  await search(lineOf('# 코드 내부 제목'));
  await md.locator('pre').waitFor();
  assert.match(await md.locator('code').textContent(), /const marker.*\n# 코드 내부 제목\n```\n/);
  assert.equal(await md.locator('h1,h2').count(), 0);
  await search(lineOf('문단 끝**'));
  await md.locator('strong').waitFor();
  assert.equal(await md.locator('strong').textContent(), '첫 문단 시작\n문단 끝');
  report.checks.push('Middle-of-table retains header/all rows; nested fence code remains code; mid-paragraph strong emphasis retains both boundaries');

  await search(lineOf('참조 [정의 링크][reference]와 각주[^가].'));
  await md.locator('sup a').waitFor();
  assert.equal(await md.getByRole('link', { name: '정의 링크' }).getAttribute('href'), 'https://example.com/reference');
  await md.locator('sup a').click();
  await page.waitForFunction(() => document.activeElement?.tagName === 'LI');
  await page.locator('.rag-drawer .footnote-backref').click();
  await page.waitForFunction(() => document.activeElement?.getAttribute('data-document-id') === 'fnref1');
  await page.keyboard.press('Escape');
  report.checks.push('Out-of-range reference definition and Korean footnote work, including return link');

  await search(lineOf('- 긴 목록 100'));
  await md.locator('li').last().waitFor();
  assert.ok(await md.locator('li').count());
  assert.equal(await md.evaluate(node => getComputedStyle(node).overflowY), 'auto');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole('button', { name: '원문 보기', exact: true }).click();
  await page.getByRole('navigation', { name: '문서 목차' }).waitFor({ state: 'visible' });
  assert.equal(await page.getByRole('navigation', { name: '문서 목차' }).evaluate(node => getComputedStyle(node).display), 'block');
  await page.screenshot({ path: path.join(output, 'outline-mobile.png') });
  await page.keyboard.press('Escape');
  report.checks.push('Server renders long lists as bounded pages; mobile outline visible with no page overflow');

  failSnapshot = true;
  await search(6);
  await card.getByRole('button', { name: '다시 시도' }).waitFor();
  assert.equal(await md.count(), 0);
  assert.ok(!await card.textContent().then(text => text.includes('BROKEN_FRAGMENT')));
  failSnapshot = false;
  await card.getByRole('button', { name: '다시 시도' }).click();
  await md.locator('ol').waitFor();
  wrongScope = true;
  await search(6);
  await card.getByRole('button', { name: '다시 시도' }).waitFor();
  assert.equal(await md.count(), 0);
  wrongScope = false;
  delaySnapshot = true;
  await search(6);
  await card.getByText('문서 구조를 불러오는 중…').waitFor();
  delaySnapshot = false;
  await search(lineOf('| 자료 | **73일** |'));
  await md.locator('table').waitFor();
  delayedSnapshots.splice(0).forEach(resolve => resolve());
  assert.ok(!await card.textContent().then(text => text.includes('STALE_DOCUMENT')));
  report.checks.push('Snapshot failure is retryable and never falls back to broken chunks; wrong-workspace response refused; cancelled stale snapshot cannot replace a newer document');
  assert.deepEqual(report.errors, []);
} finally {
  renderer.close();
  delayedSnapshots.splice(0).forEach(resolve => resolve());
  await browser?.close();
  server.kill('SIGTERM');
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
