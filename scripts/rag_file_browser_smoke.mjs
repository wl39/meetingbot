/** Folder navigation, issue priority, and explicit review acceptance UI checks. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime/rag-file-browser-qa');
await mkdir(output, { recursive: true });
const base = 'http://127.0.0.1:5198';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5198', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
let browser;
const errors = [], checks = [];
try {
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(r => setTimeout(r, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  const job = { job_id: 'job', state: 'PARTIAL', revision_id: 'r1', cancel: 0, result: { stage: 'PARTIAL', chunks: 1, documents: [{}], files: [
    { relative_path: '안내.md', state: 'PROCESSED' },
    { relative_path: '운영/기록/회의.txt', state: 'PROCESSED' },
    { relative_path: '회계/예산.xlsx', state: 'FAILED', reason: 'TABLE_HEADER_REVIEW_REQUIRED' },
  ] } };
  const ws = { id: 'qa', name: '폴더 탐색 검증', state: 'REGISTERED', document_count: 0, active_revision_id: null, consent: 'qa-provider', source: { kind: 'upload', label: '업무 자료' }, latest_job: job };
  const diagnostics = { model: { state: 'READY' }, llm: { global_allowed: true, configured: true, provider_id: 'qa-provider' }, limits: {} };
  let accepted = false, releaseRequest, responseStatus = 'answered';
  const evidence = { workspace_id: "qa", revision_id: "r1", evidence_id: "e1", relative_path: "회계/예산.xlsx", text: "예산 900", title_path: ["예산"], location: { type: "table", sheet: "예산", start_row: 2, end_row: 2, cell_range: "A2:B2" } };
  await page.route('**/api/**', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname.replace('/api/rag', '');
    let data = {};
    if (url.pathname === '/api/system/theme') data = { color: '#b85c12' };
    else if (url.pathname === '/api/events') data = {};
    else if (url.pathname === '/api/access/session') data = { authenticated: true, role: 'superadmin', demo: false, csrf: 'qa', limits: {} };
    else if (url.pathname === '/api/stt/health') data = { engine: 'real', default_model: 'small', limits: { file_seconds: 18000, file_mb: 4096, live_seconds: 300 }, active_session: null, workers: { asr: { ready: true }, diar: { ready: true }, vad: { ready: true } }, environment: {} };
    else if (url.pathname === '/api/stt/sessions') data = [];
    else if (url.pathname === '/api/stt/meeting/workspaces' || p === '/workspaces') data = [ws];
    else if (url.pathname === '/api/stt/meeting/diagnostics' || p === '/diagnostics') data = diagnostics;
    else if (p === '/auth/session') data = { csrf: 'qa' };
    else if (p === '/workspaces/qa') data = ws;
    else if (p.endsWith('/revisions')) data = [{ id: 'r1', state: job.state, created_at: Date.now() / 1000, manifest: job.result }];
    else if (p.endsWith('/questions') && req.method() === 'GET') data = [];
    else if (p.endsWith('/questions') || p.endsWith('/search')) {
      await new Promise(resolve => { releaseRequest = resolve; });
      data = { ...evidence, request_id: 'q1', query: req.postDataJSON().query, status: responseStatus, answer: responseStatus === 'related_evidence' ? '내년 예산의 직접 자료는 없지만, 관련 예산 자료에는 900으로 기록되어 있습니다.' : '예산은 900입니다.', evidence: [evidence], citations: ['e1'], timings_ms: {} };
    }
    else if (p.endsWith('/documents')) data = { evidence };
    else if (p.includes('/evidence/')) {
      const sheet = url.searchParams.get('sheet') || '예산';
      const pageIndex = Number(url.searchParams.get('page') || 0);
      data = {workspace_id:'qa',revision_id:'r1',document:{kind:'spreadsheet_page',sheet,sheets:[{name:'예산',rows:80},{name:'메모',rows:2}],columns:['A','B'],rows:[{row:pageIndex*40+1,cells:[{address:`A${pageIndex*40+1}`,value:sheet==='메모'?'보관':'원두명'},{address:`B${pageIndex*40+1}`,value:sheet==='메모'?'73일':'금액'}]}],page:pageIndex,total_pages:2,previous_page:pageIndex?0:null,next_page:pageIndex?null:1,merged_ranges:[],truncated:false}};
    }
    else if (p.endsWith('/index-jobs')) {
      assert.equal(req.postDataJSON().allow_review, true);
      accepted = true;
      job.state = 'READY'; job.result.stage = 'READY'; job.result.review_accepted = true;
      job.result.files[2].state = 'REVIEWED';
      ws.active_revision_id = 'r1'; ws.state = 'READY'; ws.document_count = 3;
      data = job;
    } else if (p === '/uploads/limits') data = { extensions: ['.md', '.txt', '.xlsx'], max_files: 2000, max_file_bytes: 1000000, max_total_bytes: 10000000, max_depth: 11, session_hours: 24 };
    else { errors.push(`Unexpected ${req.method()} ${url.pathname}`); return route.fulfill({ status: 404, json: {} }); }
    await route.fulfill({ json: data });
  });
  await page.goto(base + '/rag');
  await page.getByRole('button').filter({ has: page.getByRole('heading', { name: ws.name }) }).click();
  await page.getByRole('button', { name: '자료 확인', exact: true }).click();
  const issues = page.getByRole('region', { name: '확인이 필요한 파일' });
  await issues.getByText('예산.xlsx', { exact: true }).waitFor();
  assert.match(await issues.innerText(), /회계/);
  assert.match(await issues.innerText(), /첫 행/);
  assert.equal(await page.locator('.rag-browser-folder').count(), 2);
  await page.locator('.rag-browser-folder button').filter({ hasText: '운영' }).click();
  await page.locator('.rag-browser-folder button').filter({ hasText: '기록' }).click();
  await page.getByText('회의.txt', { exact: true }).waitFor();
  await page.getByRole('button', { name: '상위 폴더로 이동' }).click();
  assert.match(await page.getByRole('navigation', { name: '현재 폴더' }).innerText(), /운영/);
  await page.getByRole('button', { name: '리스트로 보기', exact: true }).click();
  assert.equal(await page.locator('.rag-browser > .rag-browser-rows .rag-file-path strong').first().innerText(), '예산.xlsx');
  checks.push('Issues pinned above directory/list views, nested folder navigation and parent navigation');
  await page.screenshot({ path: path.join(output, 'workspace-issues.png'), fullPage: true });
  await page.getByRole('button', { name: '경고 무시하고 사용', exact: true }).click();
  await page.getByText('경고 포함 자료 사용 중', { exact: true }).waitFor();
  assert.equal(accepted, true);
  await page.getByRole('button', { name: '회계/예산.xlsx 문서 열기', exact: true }).first().click();
  await page.getByRole('dialog', { name: '문서 원문' }).waitFor();
  await page.getByRole('tab', { name: /^메모/ }).click();
  await page.getByText('73일', { exact: true }).waitFor();
  await page.getByRole('tab', { name: /^예산/ }).click();
  await page.getByRole('button', { name: '다음 행', exact: true }).click();
  await page.getByRole('cell', { name: '원두명', exact: true }).waitFor();
  assert.match(await page.locator('.rag-document-pagination').innerText(), /41–41행/);
  await page.screenshot({ path: path.join(output, 'spreadsheet-view.png'), fullPage: true });
  await page.getByRole('button', { name: '원문 닫기' }).click();
  checks.push('File name opens full workbook with sheet tabs and row pagination');
  await page.getByRole('button', { name: '검색과 질문', exact: true }).click();
  await page.getByLabel('검색 질문').fill('예산');
  await page.getByRole('button', { name: '문서 검색', exact: true }).waitFor({ state: 'visible' });
  await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent.trim() === '문서 검색')?.disabled);
  checks.push('Explicit review acceptance sends allow_review and enables search');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  await page.getByRole('button', { name: '자료 확인 · 답변 생성 중…', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '문서 검색', exact: true }).locator('.rag-spin').count(), 0);
  assert.equal(await page.locator('.rag-search-actions .rag-spin').count(), 1);
  while (!releaseRequest) await new Promise(r => setTimeout(r, 10));
  releaseRequest(); releaseRequest = null;
  await page.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  await page.getByRole('button', { name: '문서 검색', exact: true }).click();
  await page.getByRole('button', { name: '문서 검색 중…', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '질문하기', exact: true }).locator('.rag-spin').count(), 0);
  assert.equal(await page.locator('.rag-search-actions .rag-spin').count(), 1);
  while (!releaseRequest) await new Promise(r => setTimeout(r, 10));
  releaseRequest(); releaseRequest = null;
  await page.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  checks.push('Only the clicked action spins during delayed question/search requests');
  responseStatus = 'related_evidence';
  await page.getByLabel('검색 질문').fill('내년 예산');
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  while (!releaseRequest) await new Promise(r => setTimeout(r, 10));
  releaseRequest(); releaseRequest = null;
  await page.getByRole('heading', { name: '관련 자료 기반 안내', exact: true }).waitFor();
  await page.getByText('내년 예산의 직접 자료는 없지만, 관련 예산 자료에는 900으로 기록되어 있습니다.', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, 'related-answer.png'), fullPage: true });
  checks.push('Related evidence displays as sourced guidance with the direct-answer limitation');
  await page.getByRole('button', { name: '워크스페이스 추가', exact: true }).click();
  await page.getByLabel('업로드할 폴더', { exact: true }).evaluate(input => {
    const transfer = new DataTransfer();
    for (const path of ['자료/운영/기록/회의.txt', '자료/운영/규정.md', '자료/회계/예산.xlsx', '자료/안내.md']) {
      const file = new File(['sample'], path.split('/').at(-1));
      Object.defineProperty(file, 'webkitRelativePath', { value: path });
      transfer.items.add(file);
    }
    input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.getByLabel('운영 폴더 전체 선택', { exact: true }).uncheck();
  await page.locator('.rag-browser-folder button').filter({ hasText: '운영' }).click();
  assert.equal(await page.getByLabel('운영/규정.md 업로드 선택').isChecked(), false);
  await page.locator('.rag-browser-folder button').filter({ hasText: '기록' }).click();
  assert.equal(await page.getByLabel('운영/기록/회의.txt 업로드 선택').isChecked(), false);
  await page.getByLabel('운영/기록/회의.txt 업로드 선택').check();
  await page.getByRole('button', { name: '리스트로 보기', exact: true }).click();
  assert.equal(await page.locator('.rag-upload-file input:checked').count(), 3);
  await page.getByRole('button', { name: '디렉토리별로 보기', exact: true }).click();
  await page.getByRole('navigation', { name: '현재 폴더' }).getByRole('button', { name: '자료', exact: true }).click();
  assert.equal(await page.getByLabel('운영 폴더 전체 선택', { exact: true }).evaluate(el => el.indeterminate), true);
  checks.push('Upload directory selection includes descendants and survives view switching');
  await page.screenshot({ path: path.join(output, 'upload-folders.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'upload-mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  checks.push('Mobile viewport has no horizontal overflow');
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, 'report.json'), JSON.stringify({ checks, errors }, null, 2));
  console.log(JSON.stringify({ checks, errors, output }, null, 2));
} finally { await browser?.close(); server.kill(); }
