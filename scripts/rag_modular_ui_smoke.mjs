import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime', 'rag-modular-qa');
await mkdir(output, { recursive: true });
const port = 5196, base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const report = { synthetic: true, checks: [], errors: [], requests: [] };
let browser;
try {
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(resolve => setTimeout(resolve, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => report.errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  const workspaces = ['a', 'b'].map(id => ({ id, name: `자료 ${id.toUpperCase()}`, description: '검증 자료', state: 'READY', document_count: 2, active_revision_id: `revision-${id}`, consent: 'synthetic', access_state: 'AVAILABLE', source: { root_id: 'root', relative_path: id }, latest_job: null }));
  const diagnostics = { model: { state: 'READY', model: 'synthetic', revision: '1', device: 'cpu', dimension: 384 }, llm: { global_allowed: true, provider_id: 'synthetic', endpoint: 'http://127.0.0.1:8317/v1', model: 'sample-model', configured: true, scope: 'local' }, access_mode: 'local', history_days: 30, versions: 'all', limits: {} };
  let config = { version: 1, base_url: 'http://127.0.0.1:8317/v1', default_model: 'sample-model', enabled: true, api_key_present: true, max_output_tokens: 2048, timeout_seconds: 60, temperature: null, reasoning_effort: null, input_chars: 12000, last_check: null };
  let prompt = { id: 'p1', sequence: 1, name: '기본 답변 지침', content: '제공된 자료의 근거를 바탕으로 질문에 정확히 답변하세요.', note: '', created_at: 1780000000, restored_from_id: null };
  let delaySearch = false, releaseSearch;
  const resultFor = (id, query) => ({ workspace_id: id, revision_id: `revision-${id}`, request_id: `request-${id}`, query, status: 'answered', answer: '보관 기간은 90일입니다.', citations: [`evidence-${id}`], evidence: [{ workspace_id: id, revision_id: `revision-${id}`, evidence_id: `evidence-${id}`, relative_path: '정책.md', text: '기록은 90일 동안 보관합니다.', title_path: ['보관'], location: { type: 'text', start_line: 2, end_line: 2 } }], timings_ms: {} });
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), routePath = url.pathname.replace('/api/rag', ''), method = request.method();
    report.requests.push({ path: url.pathname, method });
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) assert.equal(request.headers()['x-csrf-token'], 'synthetic-csrf');
    let data;
    if (url.pathname === '/api/system') data = { platform: { os: 'Darwin', machine: 'arm64', python: '3.12' }, selection: { engine: 'mlx', model: 'small' }, engines: [], models: [], workers: { asr: { ready: true }, diar: { ready: true } }, active_session: null, busy: false, jobs: [], updates: { supported: false, reason: 'synthetic' }, storage: { free_bytes: 1024 ** 3 } };
    else if (routePath === '/auth/session') data = { csrf: 'synthetic-csrf' };
    else if (routePath === '/workspaces') data = workspaces;
    else if (routePath === '/diagnostics') data = diagnostics;
    else if (/^\/workspaces\/[ab]$/.test(routePath)) data = workspaces.find(w => routePath.endsWith(w.id));
    else if (routePath.endsWith('/revisions')) data = [{ id: `revision-${routePath.split('/')[2]}`, state: 'READY', created_at: 1780000000, manifest: {} }];
    else if (routePath.endsWith('/questions') && method === 'GET') data = [resultFor(routePath.split('/')[2], '이전 질문')];
    else if (routePath.endsWith('/search') || routePath.endsWith('/questions')) {
      data = resultFor(routePath.split('/')[2], request.postDataJSON().query);
      if (delaySearch) { delaySearch = false; await new Promise(resolve => { releaseSearch = resolve; }); }
    }
    else if (routePath.includes('/evidence/')) data = { workspace_id: routePath.split('/')[2], revision_id: url.searchParams.get('revision_id'), document: { kind: 'rendered_page', html: '<h1 data-document-anchor="보관">보관</h1><p>기록은 90일 동안 보관합니다.</p>', start_line: 1, end_line: 2, page: 0, last_page: 0, total_pages: 1, next_page: null, previous_page: null, headings: [{ anchor: '보관', title: '보관', level: 1, page: 0, line: 1 }], outline_offset: 0, outline_total: 1, anchor_found: true, continued: false } };
    else if (routePath === '/llm/settings') {
      if (method === 'PATCH') { const body = request.postDataJSON(); assert.equal(body.expected_version, config.version); config = { ...config, ...body, version: config.version + 1 }; }
      data = config;
    }
    else if (routePath === '/llm/models' || routePath === '/llm/models/refresh') data = { models: ['sample-model', 'second-model'] };
    else if (routePath === '/llm/codex/status') data = { installed: true, connected: true, account_count: 1 };
    else if (routePath === '/llm/check') data = { models_ok: true, completion_ok: true, json_ok: true, model: config.default_model, checked_at: 1780000000 };
    else if (routePath === '/prompts' && method === 'POST') { const body = request.postDataJSON(); assert.equal(body.expected_active_id, prompt.id); prompt = { ...prompt, ...body, id: 'p2', sequence: 2 }; data = { prompt, active_id: prompt.id }; }
    else if (routePath === '/prompts') data = { active_id: prompt.id, versions: [prompt] };
    else if (routePath === '/prompts/active' || routePath === `/prompts/${prompt.id}`) data = prompt;
    else if (routePath === '/prompts/preview') { assert.equal(request.postDataJSON().case, 'conflict'); data = { synthetic: true, model: config.default_model, messages: [{ role: 'system', content: request.postDataJSON().content }] }; }
    else if (routePath === '/uploads/limits') data = { max_files: 500, max_file_bytes: 52428800, max_total_bytes: 524288000, extensions: ['.md'] };
    else if (routePath === '/source-roots') data = { roots: [{ id: 'root', label: '공유 자료' }] };
    else if (routePath === '/source-roots/root/entries') data = { entries: [{ name: '프로젝트', kind: 'directory', reason: null }], next_cursor: null };
    else { report.errors.push(`Unexpected ${method} ${url.pathname}`); return route.fulfill({ status: 404, json: { message: 'Unexpected fixture API' } }); }
    await route.fulfill({ json: data }).catch(() => {});
  });

  await page.goto(base + '/rag');
  await page.getByRole('button', { name: '워크스페이스 만들기', exact: true }).waitFor();
  await page.locator('.rag-spaces button').filter({ hasText: '자료 A' }).click();
  await page.getByLabel('검색 질문', { exact: true }).fill('작성 중인 질문');
  await page.getByRole('button', { name: '자료 관리', exact: true }).click();
  await page.getByRole('heading', { name: '자료 버전', exact: true }).waitFor();
  await page.getByRole('button', { name: '검색과 질문', exact: true }).click();
  assert.equal(await page.getByLabel('검색 질문', { exact: true }).inputValue(), '작성 중인 질문');
  await page.getByRole('button', { name: '근거 검색', exact: true }).click();
  await page.getByRole('button', { name: '원문 보기', exact: true }).click();
  await page.locator('.rag-source-lines .highlight').filter({ hasText: '90일' }).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(), 0);
  report.checks.push('Workspace tab changes preserve query; search opens source snapshot; Escape closes drawer');

  delaySearch = true;
  await page.getByRole('button', { name: '근거 검색', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.rag-search-actions button.rag-primary')?.disabled);
  await page.locator('.rag-spaces button').filter({ hasText: '자료 B' }).click();
  const releaseDeadline = Date.now() + 10000;
  while (!releaseSearch) { assert(Date.now() < releaseDeadline, 'delayed request should reach fixture'); await new Promise(resolve => setTimeout(resolve, 20)); }
  releaseSearch();
  await page.getByLabel('검색 질문', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('검색 질문', { exact: true }).inputValue(), '');
  assert.equal(await page.locator('.rag-evidence-card').count(), 0);
  await page.locator('.rag-history button').click();
  assert.equal(await page.getByLabel('검색 질문', { exact: true }).inputValue(), '이전 질문');
  report.checks.push('Workspace switch clears state and discards delayed request; history selection restores question');

  await page.getByRole('button', { name: 'AI 설정', exact: true }).click();
  await page.getByLabel('기본 모델', { exact: true }).selectOption('second-model');
  await page.getByRole('button', { name: '프롬프트 관리', exact: true }).click();
  await page.locator('.rag-ai-editor').fill('수정한 작성 지침입니다. 근거를 반드시 확인해서 답변하세요.');
  await page.locator('.rag-ai-prompt-grid select').selectOption('conflict');
  await page.getByRole('button', { name: '연결 · 기본 모델', exact: true }).click();
  assert.equal(await page.getByLabel('기본 모델', { exact: true }).inputValue(), 'second-model');
  await page.getByRole('button', { name: '설정 저장', exact: true }).click();
  await page.getByText('모든 변경 내용이 저장되었습니다.', { exact: true }).waitFor();
  assert.equal(config.default_model, 'second-model');
  await page.getByRole('button', { name: '연결 확인', exact: true }).click();
  await page.getByText('답변 생성 확인됨', { exact: true }).waitFor();
  await page.getByRole('button', { name: '프롬프트 관리', exact: true }).click();
  assert.equal(await page.locator('.rag-ai-editor').inputValue(), '수정한 작성 지침입니다. 근거를 반드시 확인해서 답변하세요.');
  assert.equal(await page.locator('.rag-ai-prompt-grid select').inputValue(), 'conflict');
  await page.getByRole('button', { name: '입력 미리보기', exact: true }).click();
  await page.locator('.rag-ai-preview pre').filter({ hasText: '수정한 작성 지침입니다.' }).waitFor();
  await page.getByRole('button', { name: '저장하고 적용', exact: true }).click();
  await page.getByText('프롬프트 v2를 저장하고 적용했습니다.', { exact: true }).waitFor();
  report.checks.push('Model and prompt drafts survive AI tabs; save/check/preview/activate preserve payloads and CSRF');
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth), false);
  await page.screenshot({ path: path.join(output, 'prompt-mobile.png'), fullPage: true });
  report.checks.push('Extracted prompt UI fits mobile viewport');

  await page.getByRole('navigation', { name: '워크스페이스 화면 전환' }).getByRole('button', { name: '자료 검색', exact: true }).click();
  await page.getByRole('button', { name: '자료 라이브러리', exact: true }).click();
  await page.getByRole('button', { name: '워크스페이스 만들기', exact: true }).click();
  await page.getByRole('button', { name: '공유 폴더 연결', exact: true }).click();
  await page.getByRole('button', { name: '프로젝트', exact: true }).click();
  await page.getByLabel('이름', { exact: true }).fill('새 공유 자료');
  assert.equal(await page.getByLabel('이름', { exact: true }).inputValue(), '새 공유 자료');
  report.checks.push('Extracted server folder browser navigates and retains workspace metadata');
  assert.deepEqual(report.errors, []);
} finally {
  await browser?.close();
  server.kill('SIGTERM');
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
