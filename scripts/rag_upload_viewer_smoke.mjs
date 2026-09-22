/** Synthetic browser checks: no real documents or external AI calls. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import { markdownFixtures } from './markdown_fixture_client.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime/rag-upload-viewer-qa');
await mkdir(output, { recursive: true });
const port = 5197, base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const report = { synthetic: true, checks: [], errors: [] };
const renderer = markdownFixtures(root);
let browser;
try {
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(resolve => setTimeout(resolve, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', error => report.errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  const ws = { id: 'qa', name: '검증 자료', description: '', state: 'READY', document_count: 2, active_revision_id: 'revision-qa', consent: null, source: { kind: 'upload', label: '자료', root_id: 'upload-qa', relative_path: '' }, latest_job: null };
  const diagnostics = { model: { state: 'READY', model: 'synthetic', revision: '1', device: 'cpu', dimension: 384 }, llm: { global_allowed: true, provider_id: 'qa-provider', endpoint: 'http://127.0.0.1:8317', model: 'sample-model', configured: true }, history_days: 30, versions: 'all', limits: {} };
  const evidence = { workspace_id: ws.id, revision_id: ws.active_revision_id, evidence_id: 'e1', relative_path: '운영/정책.md', text: '기록은 90일 보관합니다.', title_path: ['보관 정책'], location: { type: 'text', start_line: 3, end_line: 3 } };
  const markdown = '# 보관 정책\n\n기록은 **90일** 보관합니다.\n\n- 보관 담당자 확인\n- [x] 검증 완료\n\n| 항목 | 기간 |\n| --- | --- |\n| 로그 | 90일 |\n\n```js\nconst days = 90;\n```\n\n<script>window.injected = true</script>\n\n![외부 이미지](https://example.invalid/pixel.png)\n\n[안전하지 않은 링크](javascript:alert(1))';
  await renderer.add('main', markdown + '\n\n## 참고 문서\n\n[연결 문서 열기](../가이드.md)');
  await renderer.add('linked', '# 연결 문서\n\n안내 내용입니다.');
  let session, failOnce = true, commits = 0, allowApproval = false, questions = 0, approvalRequests = 0, role = 'superadmin';
  // Deliberately broken retrieval fragment inside a table, not a full document.
  evidence.text = '로그 | 90일 |';
  evidence.location = { type: 'text', start_line: 10, end_line: 10 };
  const uploads = [];
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname.replace('/api/rag', ''), method = request.method();
    let data;
    if (url.pathname === '/api/system/theme') data = { color: '#b85c12' };
    else if (url.pathname === '/api/events') data = {};
    else if (url.pathname === '/api/access/session') data = { authenticated: true, role, demo: false, csrf: 'qa-csrf', limits: {} };
    else if (url.pathname === '/api/stt/health') data = { engine: 'real', default_model: 'small', limits: { file_seconds: 18000, file_mb: 4096, live_seconds: 300 }, active_session: null, workers: { asr: { ready: true }, diar: { ready: true }, vad: { ready: true } }, environment: { machine: 'Apple M1', system: 'macOS' } };
    else if (url.pathname === '/api/stt/sessions') data = [];
    else if (url.pathname === '/api/stt/meeting/workspaces') data = [ws];
    else if (url.pathname === '/api/stt/meeting/diagnostics') data = diagnostics;
    else if (p === '/auth/session') data = { csrf: 'qa-csrf' };
    else if (p === '/workspaces') data = [ws];
    else if (p === '/diagnostics') data = diagnostics;
    else if (p.endsWith('/meeting/policy')) data = { version: 1, priority_response_target_seconds: 30, pressure_ratio: 0.6, protect_ratio: 0.8, recovery_ratio: 0.4, recovery_seconds: 3, context_wait_seconds: 1, filter_model: '', filter_timeout_seconds: 5, generation_timeout_seconds: 20, scope_profile: { description: '', included_topics: [], excluded_topics: [], aliases: [] } };
    else if (p === '/uploads/limits') data = { extensions: ['.md', '.txt'], max_files: 2000, max_file_bytes: 1000000, max_total_bytes: 10000000, max_depth: 11, session_hours: 24 };
    else if (p === '/uploads' && method === 'POST') {
      session = { id: 'session', state: 'OPEN', files: request.postDataJSON().files.map((f, i) => ({ ...f, id: String(i), received: false })) };
      data = session;
    } else if (p === '/uploads/session' && method === 'GET') data = session;
    else if (p === '/uploads/session' && method === 'DELETE') data = {};
    else if (p.startsWith('/uploads/session/files/')) {
      const file = session.files.find(f => f.id === p.split('/').at(-1));
      uploads.push(file.path);
      if (file.id === '1' && failOnce) {
        failOnce = false;
        return route.fulfill({ status: 503, json: { message: '검증용 일시적 연결 오류' } });
      }
      file.received = true;
      data = {};
    } else if (p === '/uploads/session/commit') { commits++; data = { workspace: ws, job: null, index_error: null }; }
    else if (p === '/workspaces/qa') {
      if (method === 'PATCH') {
        approvalRequests++;
        assert.equal(request.postDataJSON().provider_id, 'qa-provider');
        if (!allowApproval) return route.fulfill({ status: 409, json: { message: '검증용 승인 저장 실패' } });
        ws.consent = 'qa-provider';
      }
      data = ws;
    } else if (p.endsWith('/revisions')) data = [];
    else if (p.endsWith('/questions') && method === 'GET') data = [];
    else if (p.endsWith('/questions') || p.endsWith('/search')) {
      if (p.endsWith('/questions')) { questions++; assert.equal(ws.consent, 'qa-provider'); }
      data = { workspace_id: ws.id, revision_id: ws.active_revision_id, request_id: 'query-1', query: request.postDataJSON().query, status: 'answered', answer: '기록은 **90일** 보관합니다.', evidence: [evidence], citations: ['e1'], timings_ms: {} };
    } else if (p.includes('/evidence/')) {
      assert.ok(url.searchParams.has('view'), 'No whole-snapshot requests');
      data = { workspace_id: ws.id, revision_id: ws.active_revision_id, document: await renderer.render(p.endsWith('/e2') ? 'linked' : 'main', p.endsWith('/e2') ? { ...evidence, location: { start_line: 1, end_line: 1 } } : evidence, url.searchParams) };
    }
    else if (p === '/workspaces/qa/documents') { assert.equal(url.searchParams.get('relative_path'), '가이드.md'); data = { evidence: { ...evidence, evidence_id: 'e2', relative_path: '가이드.md' } }; }
    else { report.errors.push(`Unexpected ${method} ${url.pathname}`); return route.fulfill({ status: 404, json: { message: 'Unexpected fixture API' } }); }
    await route.fulfill({ json: data });
  });
  await page.goto(base + '/rag');
  await page.getByRole('button', { name: '워크스페이스 추가', exact: true }).click();
  await page.getByLabel('업로드할 파일', { exact: true }).setInputFiles(Array.from({ length: 205 }, (_, i) => ({ name: `자료-${i}.md`, mimeType: 'text/markdown', buffer: Buffer.from('# 자료') })));
  assert.equal(await page.locator('.rag-upload-file input').count(), 200);
  await page.getByRole('button', { name: '파일 더 보기 (200 / 205)', exact: true }).click();
  await page.getByLabel('자료-204.md 업로드 선택', { exact: true }).uncheck();
  assert.equal(await page.locator('.rag-upload-file input:checked').count(), 204);
  report.checks.push('Every file beyond the first 200 can be displayed and individually selected');
  await page.getByLabel('업로드할 폴더', { exact: true }).evaluate(input => {
    const transfer = new DataTransfer();
    for (const path of ['자료/운영/정책.md', '자료/팀/회의.md', '자료/제외.txt']) {
      const file = new File(['# 검증 자료'], path.split('/').at(-1), { type: 'text/plain' });
      Object.defineProperty(file, 'webkitRelativePath', { value: path });
      transfer.items.add(file);
    }
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.getByRole('button', { name: '리스트로 보기', exact: true }).click();
  assert.equal(await page.locator('.rag-upload-file .rag-file-path strong').first().textContent(), '정책.md');
  assert.equal(await page.locator('.rag-upload-file .rag-file-folder').first().textContent(), '운영');
  await page.getByRole('button', { name: '전체 해제', exact: true }).click();
  assert.equal(await page.locator('.rag-upload-file input:checked').count(), 0);
  assert.equal(await page.getByRole('button', { name: '문서 등록', exact: true }).isDisabled(), true);
  await page.getByRole('button', { name: '전체 선택', exact: true }).click();
  assert.equal(await page.locator('.rag-upload-file input:checked').count(), 3);
  await page.getByLabel('제외.txt 업로드 선택', { exact: true }).uncheck();
  await page.getByRole('button', { name: '문서 등록', exact: true }).click();
  await page.getByRole('button', { name: '이어서 재시도', exact: true }).waitFor();
  assert.equal(await page.locator('.rag-upload-file b.completed').count(), 1);
  assert.equal(await page.locator('.rag-upload-file b.failed').count(), 1);
  assert.equal(await page.getByLabel('운영/정책.md 업로드 선택', { exact: true }).isDisabled(), true);
  assert.deepEqual(session.files.map(f => f.path), ['운영/정책.md', '팀/회의.md']);
  await page.getByRole('button', { name: '이어서 재시도', exact: true }).click();
  await page.getByRole('button', { name: '워크스페이스 열기', exact: true }).waitFor();
  assert.equal(await page.locator('.rag-upload-file b.completed').count(), 2);
  assert.deepEqual(uploads, ['운영/정책.md', '팀/회의.md', '팀/회의.md']);
  assert.equal(commits, 1);
  await page.screenshot({ path: path.join(output, 'upload-completed.png'), fullPage: true });
  report.checks.push('Select all/none/individual, selected-only manifest, per-file success/failure, resume skips received files, completion stays visible');

  await page.getByRole('button', { name: '워크스페이스 열기', exact: true }).click();
  await page.getByLabel('검색 질문', { exact: true }).fill('기록은 얼마나 보관하나요?');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await page.getByText('검증용 승인 저장 실패', { exact: true }).waitFor();
  assert.equal(questions, 0);
  allowApproval = true;
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await page.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  assert.equal(questions, 1);
  assert.equal(approvalRequests, 2);
  assert.equal(await page.locator('.rag-answer strong').textContent(), '90일');
  await page.locator('.rag-evidence-card .rag-markdown table').waitFor();
  assert.equal(await page.locator('.rag-evidence-card .rag-markdown th').count(), 2);
  assert.ok(!/sample-model|외부 전송|AI|LLM|CPU|GPU/.test(await page.locator('body').innerText()));
  await page.getByRole('button', { name: '원문 보기', exact: true }).click();
  await page.getByRole('navigation', { name: '문서 목차' }).getByRole('button', { name: '보관 정책', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown h1').waitFor();
  assert.equal(await page.locator('.rag-drawer .rag-markdown table tbody tr').count(), 1);
  assert.equal(await page.locator('.rag-drawer .rag-markdown pre code').textContent(), 'const days = 90;\n');
  assert.equal(await page.locator('.rag-drawer .rag-markdown img,.rag-drawer .rag-markdown script,.rag-drawer a[href^="javascript:"]').count(), 0);
  assert.equal(await page.evaluate(() => window.injected), undefined);
  assert.equal(await page.locator('.rag-drawer header .rag-file-path strong').textContent(), '정책.md');
  assert.equal(await page.locator('.rag-drawer header .rag-file-folder').textContent(), '운영');
  await page.screenshot({ path: path.join(output, 'markdown-desktop.png'), fullPage: true });
  assert.equal(await page.getByRole('navigation', { name: '문서 목차' }).count(), 1);
  await page.getByRole('link', { name: '연결 문서 열기', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown h1').filter({ hasText: '연결 문서' }).waitFor();
  await page.getByRole('button', { name: '이전 문서', exact: true }).click();
  await page.getByRole('navigation', { name: '문서 목차' }).getByRole('button', { name: '보관 정책', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown h1').filter({ hasText: '보관 정책' }).waitFor();
  report.checks.push('Search cards render Markdown; product UI hides model/implementation details; document outline and relative-link navigation work');
  await page.getByRole('button', { name: '원문 · 줄 번호', exact: true }).click();
  await page.locator('.rag-source-lines .highlight').waitFor();
  assert.equal(await page.locator('.rag-source-lines .highlight').count(), 1);
  await page.getByRole('button', { name: '문서 보기', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown').waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'markdown-mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  report.checks.push('Approval failure never sends question; successful approval retries answer; Markdown headings/tables/code, safe HTML/links, source line toggle, folder label, mobile width');
  await page.keyboard.press('Escape');
  ws.consent = null;
  await page.goto(base + '/live');
  await page.getByRole('button', { name: '회의 검토 시작', exact: true }).click();
  await page.getByRole('button', { name: '검토 종료', exact: true }).waitFor();
  assert.equal(approvalRequests, 3);
  assert.ok(!/sample-model|외부 전송|AI|LLM|Apple M1|Mac GPU|CPU|GPU/.test(await page.locator('body').innerText()));
  await page.screenshot({ path: path.join(output, 'meeting-service.png'), fullPage: true });
  report.checks.push('Meeting review activates workspace use through an administrator action; customer copy contains no model or hardware details');
  role = 'visitor'; ws.consent = null;
  await page.goto(base + '/rag');
  await page.locator('.rag-spaces button').filter({ hasText: ws.name }).click();
  await page.getByLabel('검색 질문', { exact: true }).fill('방문자 질문');
  assert.equal(await page.getByRole('button', { name: '질문하기', exact: true }).isDisabled(), true);
  assert.equal(approvalRequests, 3);
  report.checks.push('Visitors cannot grant workspace consent');
  assert.deepEqual(report.errors, []);
} finally {
  renderer.close();
  await browser?.close();
  server.kill('SIGTERM');
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
