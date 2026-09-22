/** Synthetic browser coverage. Every API response is an explicit fixture; no live account data is used. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime', 'onboarding-qa');
await mkdir(output, { recursive: true });
const port = Number(process.env.ONBOARDING_QA_PORT || 5209);
const base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], {
  cwd: path.join(root, 'frontend'), stdio: 'ignore',
});
const report = { synthetic: true, checks: [], errors: [], requests: [] };
const diagnostics = { model: { state: 'READY' }, llm: { global_allowed: true, configured: true, provider_id: 'fixture-provider' }, history_days: 30, limits: {} };
const ownWorkspace = {
  id: 'a'.repeat(32), name: '제품팀 회의 자료', description: '제품 운영 안내', state: 'READY', document_count: 1,
  active_revision_id: 'revision-own', consent: 'fixture-provider', can_manage: true, visibility: 'private',
  access_state: 'AVAILABLE', source: { kind: 'upload', label: '제품팀 문서' }, latest_job: null,
};
const recipeWorkspace = {
  ...ownWorkspace, id: 'b'.repeat(32), name: '한국 인기 요리 레시피', description: '체험용 요리 문서',
  active_revision_id: 'revision-recipes', source: { kind: 'upload', label: 'tutorial-recipes' },
};
const delay = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
let browser;

async function createFixturePage({ sample = false, mobile = false } = {}) {
  const page = await browser.newPage({ viewport: mobile ? { width: 390, height: 844 } : { width: 1440, height: 1000 } });
  page.setDefaultTimeout(12000);
  page.on('pageerror', error => report.errors.push(error.message));
  let workspaces = sample ? [] : [ownWorkspace];
  let pendingRecipe = false;
  let requestSequence = 0;
  const results = new Map();
  const fixture = { page, searchCount: 0, uploadCount: 0, fileCount: 0, commitCount: 0, holdSearch: false, releaseSearch: null, recipePolls: 0 };
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method();
    report.requests.push({ scenario: sample ? 'new-sample' : 'existing-documents', path: pathname, method });
    let data;
    try {
      if (pathname.startsWith('/api/rag/') && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method))
        assert.equal(request.headers()['x-csrf-token'], 'fixture-csrf');
      if (pathname === '/api/access/session') data = {
        authenticated: true, role: 'visitor', account: { id: sample ? 'sample-user' : 'own-user', label: '체험 사용자', role: 'visitor' },
        keyless: true, demo: false, csrf: 'fixture-csrf', limits: { seconds: 300, file_mb: 30, jobs_per_visitor: 5, jobs_daily: 50 },
      };
      else if (pathname === '/api/system/theme') data = { color: '#b85c12' };
      else if (pathname === '/api/events') data = {};
      else if (pathname === '/api/rag/auth/session') data = { csrf: 'fixture-csrf' };
      else if (pathname === '/api/rag/workspaces' || pathname === '/api/stt/meeting/workspaces') data = workspaces;
      else if (pathname === '/api/rag/diagnostics' || pathname === '/api/stt/meeting/diagnostics') data = diagnostics;
      else if (pathname === '/api/stt/health') data = {
        engine: 'real', default_model: 'small', active_session: null, management_busy: false,
        limits: { file_mb: 30, file_seconds: 300, live_seconds: 300 }, environment: { machine: 'fixture', system: 'fixture' },
        workers: { asr: { ready: true }, diar: { ready: true } },
      };
      else if (pathname === '/api/stt/sessions') data = [];
      else if (pathname === '/api/rag/uploads/limits') data = { max_files: 500, max_file_bytes: 52428800, max_total_bytes: 524288000, extensions: ['.md', '.txt'] };
      else if (pathname === '/api/rag/uploads' && method === 'POST') {
        const body = request.postDataJSON();
        assert.equal(body.name, recipeWorkspace.name);
        assert.equal(body.files[0].path, 'korean-recipes.md');
        assert(body.files[0].size > 100);
        fixture.uploadCount++;
        data = { id: 'tutorial-upload', files: [{ id: 'recipe-file', path: 'korean-recipes.md', received: false }] };
      }
      else if (pathname === '/api/rag/uploads/tutorial-upload/files/recipe-file' && method === 'PUT') {
        assert.match(request.postDataBuffer().toString('utf8'), /김치볶음밥/);
        fixture.fileCount++;
        data = { received: true };
      }
      else if (pathname === '/api/rag/uploads/tutorial-upload/commit' && method === 'POST') {
        fixture.commitCount++;
        pendingRecipe = true;
        const pending = { ...recipeWorkspace, state: 'RUNNING', document_count: 0, active_revision_id: null,
          latest_job: { job_id: 'recipe-job', state: 'RUNNING', revision_id: 'revision-recipes', result: {} } };
        workspaces = [pending];
        data = { workspace: pending, job: pending.latest_job, index_error: null };
      }
      else if (/^\/api\/rag\/workspaces\/[^/]+$/.test(pathname)) {
        const id = pathname.split('/').at(-1);
        if (id === recipeWorkspace.id && pendingRecipe) {
          fixture.recipePolls++;
          pendingRecipe = false;
          workspaces = [recipeWorkspace];
        }
        data = workspaces.find(workspace => workspace.id === id);
        assert(data, `known workspace ${id}`);
      }
      else if (pathname.endsWith('/revisions')) data = [];
      else if (pathname.endsWith('/questions') && method === 'GET') data = [...results.values()].filter(result => pathname.includes(result.workspace_id));
      else if ((pathname.endsWith('/search') || pathname.endsWith('/questions')) && method === 'POST') {
        const workspaceId = pathname.split('/')[4], workspace = workspaces.find(item => item.id === workspaceId);
        assert(workspace?.active_revision_id);
        const { query } = request.postDataJSON();
        assert(query.trim());
        fixture.searchCount++;
        if (fixture.holdSearch) {
          fixture.holdSearch = false;
          await new Promise(resolve => { fixture.releaseSearch = resolve; });
        }
        data = {
          request_id: (++requestSequence).toString(16).padStart(32, '0'), workspace_id: workspaceId, revision_id: workspace.active_revision_id,
          query, status: 'evidence_found', answer: null, created_at: 1789000000, citations: [],
          evidence: [{ evidence_id: 'fixture-evidence', workspace_id: workspaceId, revision_id: workspace.active_revision_id,
            relative_path: '문서.txt', title_path: ['안내'], location: { type: 'text', start_line: 1, end_line: 1 },
            text: sample ? '김치볶음밥에는 밥, 김치, 대파가 필요합니다.' : '제품팀은 매주 월요일 회의를 진행합니다.' }],
          timings_ms: {},
        };
        results.set(data.request_id, data);
      }
      else if (pathname.startsWith('/api/rag/history/')) {
        const result = results.get(pathname.split('/').at(-1));
        assert(result, 'saved history fixture');
        data = { id: result.request_id, subject: sample ? 'sample-user' : 'own-user', created_at: result.created_at,
          workspace_name: workspaces.find(item => item.id === result.workspace_id)?.name, result };
      }
      else throw new Error(`Unexpected fixture request: ${method} ${pathname}`);
      await route.fulfill({ json: data }).catch(() => {});
    } catch (error) {
      report.errors.push(error.message);
      await route.fulfill({ status: 500, json: { message: '브라우저 검증 응답 오류' } }).catch(() => {});
    }
  });
  return fixture;
}

async function assertCleanCopy(page) {
  const text = await page.locator('body').innerText();
  for (const banned of ['1·2점', '3점 보조큐', '4·5점 우선큐', '우선큐', '보조큐', '전사 준비 완료', '전사 준비완료', '준비된 문서', '회의 기록 · 지식 관리', '이전 자료 재사용', '질문 ID:'])
    assert(!text.includes(banned), `visible copy must omit ${banned}`);
  assert.equal(await page.locator('.rag-metrics').count(), 0, 'global workspace/document totals were removed');
}

async function assertFits(page, label) {
  const layout = await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth,
    modal: document.querySelector('dialog[open]')?.getBoundingClientRect().toJSON() }));
  assert(layout.scroll <= layout.width, `${label}: no page overflow (${layout.scroll}/${layout.width})`);
  if (layout.modal) assert(layout.modal.left >= 0 && layout.modal.right <= layout.width, `${label}: dialog fits viewport`);
}

async function screenshot(page, name) {
  await page.evaluate(() => new Promise(resolve => {
    window.scrollTo(0, 0);
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
  await page.screenshot({ path: path.join(output, name), fullPage: true });
}

try {
  let ready = false;
  for (let i = 0; i < 80; i++) { try { const response = await fetch(base); if (response.ok) { ready = true; break; } } catch {} await delay(100); }
  assert(ready, 'Vite fixture server started');
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const own = await createFixturePage();
  const page = own.page;
  await page.goto(base + '/rag');
  const welcome = page.getByRole('dialog', { name: '회의에 사용할 문서들이 준비되었나요?' });
  await welcome.waitFor();
  assert(await page.evaluate(() => !!document.querySelector('dialog:modal')?.contains(document.activeElement)), 'welcome owns initial keyboard focus');
  await welcome.getByRole('button', { name: '나중에 둘러볼게요', exact: true }).focus();
  await page.keyboard.press('Tab');
  assert(await page.evaluate(() => document.activeElement === document.body || !!document.querySelector('dialog:modal')?.contains(document.activeElement)), 'Tab does not enter background application controls');
  if (await page.evaluate(() => document.activeElement === document.body)) await page.keyboard.press('Tab');
  assert(await page.evaluate(() => !!document.querySelector('dialog:modal')?.contains(document.activeElement)), 'Tab returns to welcome after the browser chrome');
  await screenshot(page, 'welcome-desktop.png');
  await welcome.getByRole('button', { name: /네, 준비되어 있어요/ }).click();
  await page.getByLabel('체험할 워크스페이스', { exact: true }).selectOption(ownWorkspace.id);
  const query = page.getByLabel('검색 질문', { exact: true });
  await query.waitFor();
  await page.waitForFunction(() => document.querySelector('textarea[aria-label="검색 질문"]')?.value?.length > 0);
  const continueVoice = page.getByRole('button', { name: '음성으로 이어서', exact: true });
  assert(await continueVoice.isDisabled(), 'search must complete before advancing');
  await query.fill('제품팀 회의는 언제 하나요?');
  own.holdSearch = true;
  await page.getByRole('button', { name: '문서 검색', exact: true }).click();
  for (let i = 0; i < 100 && !own.releaseSearch; i++) await delay(20);
  assert.equal(own.searchCount, 1, 'real UI dispatched one search POST');
  assert(await continueVoice.isDisabled(), 'pending search does not unlock the next step');
  own.releaseSearch();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.includes('음성으로 이어서') && !button.disabled));
  await page.getByText('제품팀은 매주 월요일 회의를 진행합니다.', { exact: true }).waitFor();
  await assertCleanCopy(page);
  await screenshot(page, 'own-workspace-search.png');
  report.checks.push('Welcome yes path selects an existing workspace, fills a question, and advances only after a completed search POST');
  await continueVoice.click();
  await page.getByRole('heading', { name: '이번에는 직접 말해보세요', exact: true }).waitFor();
  await page.waitForFunction(id => document.querySelector('#meeting-workspace')?.value === id, ownWorkspace.id);
  assert(await page.getByRole('button', { name: '파일로 이어서', exact: true }).isDisabled());
  await page.getByRole('button', { name: '마이크 사용이 어려워요 · 건너뛰기', exact: true }).click();
  await page.getByRole('heading', { name: '녹음 파일도 같은 방법으로 확인하세요', exact: true }).waitFor();
  assert(await page.getByRole('button', { name: '체험 마치기', exact: true }).isDisabled());
  await page.getByRole('button', { name: '파일 업로드는 다음에 할게요', exact: true }).click();
  await page.getByRole('heading', { name: '이제 내 회의에 활용해 보세요', exact: true }).waitFor();
  await assertCleanCopy(page);
  await page.getByRole('button', { name: '시작하기', exact: true }).click();
  await page.reload();
  await page.getByLabel('검색 질문', { exact: true }).waitFor();
  assert.equal(await page.locator('dialog[open]').count(), 0, 'dismissed tutorial stays dismissed after reload');
  const reopen = page.getByRole('button', { name: '사용 가이드', exact: true });
  await reopen.click();
  await welcome.waitFor();
  await page.keyboard.press('Escape');
  await welcome.waitFor({ state: 'hidden' });
  assert(await reopen.evaluate(element => element === document.activeElement), 'Escape restores focus to the guide button');
  report.checks.push('Microphone and audio-file steps offer skips; completion persists after reload; guide can reopen and Escape restores focus');

  const sample = await createFixturePage({ sample: true, mobile: true });
  const mobile = sample.page;
  await mobile.goto(base + '/rag');
  await mobile.getByRole('dialog').waitFor();
  await assertFits(mobile, '390px welcome');
  await screenshot(mobile, 'welcome-mobile.png');
  await mobile.getByRole('button', { name: /아니요, 먼저 체험할게요/ }).click();
  const recipe = mobile.getByRole('button', { name: /한국 인기 요리 레시피/ });
  await recipe.waitFor();
  assert(await mobile.getByRole('button', { name: /^모닝브루/ }).isDisabled(), 'unavailable Morning Brew is explained and disabled');
  await assertFits(mobile, '390px sample choices');
  await recipe.click();
  await mobile.getByLabel('검색 질문', { exact: true }).waitFor();
  await mobile.waitForFunction(() => document.querySelector('textarea[aria-label="검색 질문"]')?.value?.includes('김치볶음밥'));
  assert.equal(sample.uploadCount, 1);
  assert.equal(sample.fileCount, 1);
  assert.equal(sample.commitCount, 1);
  assert(sample.recipePolls > 0, 'search waits for the committed sample to become usable');
  await mobile.getByRole('button', { name: '문서 검색', exact: true }).click();
  await mobile.getByText('김치볶음밥에는 밥, 김치, 대파가 필요합니다.', { exact: true }).waitFor();
  assert.equal(sample.searchCount, 1);
  assert.equal(await mobile.getByRole('button', { name: '음성으로 이어서', exact: true }).isDisabled(), false);
  await assertFits(mobile, '390px sample search');
  await assertCleanCopy(mobile);
  await screenshot(mobile, 'sample-search-mobile.png');
  await mobile.getByRole('button', { name: '가이드 닫기', exact: true }).click();
  await mobile.reload();
  await mobile.getByLabel('검색 질문', { exact: true }).waitFor();
  assert.equal(await mobile.getByRole('region', { name: '시작 가이드', exact: true }).count(), 0);
  assert.equal(await mobile.locator('dialog[open]').count(), 0);
  await mobile.getByRole('button', { name: '사용 가이드', exact: true }).click();
  await mobile.getByRole('dialog').waitFor();
  await mobile.keyboard.press('Escape');
  await mobile.getByRole('dialog').waitFor({ state: 'hidden' });
  await assertFits(mobile, '390px reopened then dismissed');
  report.checks.push('No-documents path uploads bundled recipe content, commits it, waits for readiness, and performs document search at 390px without overflow');
  report.checks.push('Both paths omit internal queues, scoring, global document totals, ready badges and question IDs from visible copy');
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = error.stack || String(error);
  throw error;
} finally {
  await browser?.close();
  server.kill('SIGTERM');
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
