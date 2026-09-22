/** Synthetic UI regression; no real workspaces are edited and no model is called. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime/workspace-guide-qa');
await mkdir(output, { recursive: true });
const base = 'http://127.0.0.1:5198';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5198', '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
const report = { synthetic: true, checks: [], errors: [] };
let browser;
try {
  for (let i = 0; i < 60; i++) { try { await fetch(base); break; } catch { await new Promise(r => setTimeout(r, 100)); } }
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', e => report.errors.push(e.message));
  await page.addInitScript(() => sessionStorage.setItem('stt-token', 'synthetic'));
  const spaces = ['요리 자료', '운영 자료'].map((name, i) => ({ id: String(i), name, description: '', state: 'READY', document_count: 1, active_revision_id: `rev-${i}`, consent: 'provider', source: { kind: 'upload', label: name }, latest_job: null }));
  const guides = Object.fromEntries(spaces.map(w => [w.id, { workspace_id: w.id, content: '', enabled: false, version: 0, content_hash: '', updated_at: null, max_chars: 4000 }]));
  let failSave = false, failLoad = false, guideReads = 0, role = 'admin';
  await page.route('**/api/**', async route => {
    const req = route.request(), p = new URL(req.url()).pathname, method = req.method();
    let data;
    if (p.endsWith('/auth/session') || p === '/api/access/session') data = { authenticated: true, role, csrf: 'synthetic', demo: false, limits: {} };
    else if (p === '/api/stt/health') data = { active_session: null, workers: {}, limits: {}, environment: {} };
    else if (p === '/api/stt/sessions') data = [];
    else if (p.endsWith('/workspaces')) data = spaces;
    else if (p.endsWith('/diagnostics')) data = { model: { state: 'READY' }, llm: { configured: true, global_allowed: true, provider_id: 'provider' }, history_days: 30 };
    else if (/\/workspaces\/\d$/.test(p)) data = spaces.find(w => p.endsWith('/' + w.id));
    else if (/\/(revisions|questions)$/.test(p)) data = [];
    else if (p.endsWith('/guide')) {
      const id = p.split('/').at(-2);
      if (method === 'PUT') {
        if (failSave) { failSave = false; return route.fulfill({ status: 503, json: { message: '일시적 저장 오류입니다.' } }); }
        const body = req.postDataJSON();
        if (body.expected_version !== guides[id].version) return route.fulfill({ status: 409, json: { error_code: 'GUIDE_CHANGED', message: '다른 화면에서 지침서가 변경되었습니다.' } });
        guides[id] = { ...guides[id], ...body, content: body.content.trim(), enabled: body.enabled && !!body.content.trim(), version: guides[id].version + 1, updated_at: Date.now() / 1000 };
      } else {
        guideReads++;
        if (failLoad) return route.fulfill({ status: 503, json: { message: '지침서 불러오기 실패' } });
      }
      data = guides[id];
    } else { report.errors.push(`Unexpected ${method} ${p}`); return route.fulfill({ status: 404, json: {} }); }
    return route.fulfill({ json: data });
  });
  const select = async name => {
    await page.locator('.rag-spaces').getByRole('button', { name: new RegExp(name) }).click();
    await page.getByRole('button', { name: '워크스페이스 설정', exact: true }).click();
    await page.getByLabel('지침서 내용', { exact: true }).waitFor();
  };
  const editor = page.getByLabel('지침서 내용', { exact: true });
  const toggle = page.getByLabel('질문과 회의 검토에 지침서 참고', { exact: true });
  const save = page.getByRole('button', { name: '지침서 저장', exact: true });
  await page.goto(base + '/rag');
  await select('요리 자료');
  assert.equal(await save.isDisabled(), true);
  assert.equal(await toggle.isChecked(), true);
  const content = '요리 관련 답변에는 재료와 조리 순서를 포함해 주세요.\n조리 순서는 번호로 정리해 주세요.';
  await editor.fill(content);
  await save.click();
  await page.getByRole('status').filter({ hasText: '지침서를 저장했습니다' }).waitFor();
  assert.equal(guides['0'].content, content);
  assert.equal(guides['0'].enabled, true);
  assert.equal(await save.isDisabled(), true);
  await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
  report.checks.push('Admin can save a per-workspace guide with clear labeling, activation and save feedback');
  await page.reload();
  await select('요리 자료');
  assert.equal(await editor.inputValue(), content);
  await select('운영 자료');
  assert.equal(await editor.inputValue(), '');
  await select('요리 자료');
  assert.equal(await editor.inputValue(), content);
  report.checks.push('Reload persists saved text; switching workspace does not leak another guide');
  await toggle.uncheck();
  await save.click();
  await page.getByRole('status').filter({ hasText: '현재 답변에는 참고하지 않습니다' }).waitFor();
  assert.equal(guides['0'].content, content);
  assert.equal(guides['0'].enabled, false);
  failSave = true;
  await editor.fill('저장 실패 후에도 남아야 하는 수정본');
  await save.click();
  await page.getByRole('alert').filter({ hasText: '일시적 저장 오류' }).waitFor();
  assert.equal(await editor.inputValue(), '저장 실패 후에도 남아야 하는 수정본');
  await page.getByRole('button', { name: '수정 취소', exact: true }).click();
  assert.equal(await editor.inputValue(), content);
  report.checks.push('Disable retains content; failed saves preserve draft; cancel restores saved text');
  guides['0'] = { ...guides['0'], content: '<script>window.guideInjected=true</script>다른 관리자의 최신 지침서', version: guides['0'].version + 1 };
  await editor.fill('내가 작성 중인 지침서');
  await save.click();
  await page.getByRole('heading', { name: '다른 화면에서 저장한 최신 지침서' }).waitFor();
  assert.equal(await save.isDisabled(), true);
  assert.equal(await editor.inputValue(), '내가 작성 중인 지침서');
  assert.equal(await page.evaluate(() => window.guideInjected), undefined);
  await page.getByRole('button', { name: '내 수정본으로 계속', exact: true }).click();
  await save.click();
  await page.getByRole('status').filter({ hasText: '지침서를 저장했습니다' }).waitFor();
  assert.equal(guides['0'].content, '내가 작성 중인 지침서');
  report.checks.push('Concurrent updates require explicit review before overwrite; latest text is escaped');
  await editor.fill('');
  await save.click();
  await page.getByRole('status').filter({ hasText: '지침서를 저장했습니다' }).waitFor();
  assert.equal(guides['0'].content, '');
  assert.equal(guides['0'].enabled, false);
  await editor.fill(content);
  await toggle.check();
  await save.click();
  await page.getByRole('status').filter({ hasText: '이후 시작하는 질문' }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, 'mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.ok(!/사용자 프롬프트|gpt-|LLM|MacBook/.test(await page.locator('.rag-guide').innerText()));
  report.checks.push('Clear disables guidance; mobile layout fits; customer copy uses 지침서');
  failLoad = true;
  await page.reload();
  await page.locator('.rag-spaces').getByRole('button', { name: /요리 자료/ }).click();
  await page.getByRole('button', { name: '워크스페이스 설정', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: '지침서 불러오기 실패' }).waitFor();
  failLoad = false;
  await page.getByRole('button', { name: '다시 불러오기', exact: true }).click();
  await editor.waitFor();
  assert.equal(await editor.inputValue(), content);
  role = 'visitor';
  const before = guideReads;
  await page.reload();
  await page.locator('.rag-spaces').getByRole('button', { name: /요리 자료/ }).click();
  await page.getByLabel('검색 질문', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '워크스페이스 설정', exact: true }).count(), 0);
  assert.equal(guideReads, before);
  report.checks.push('Failed loading is retryable; visitors never fetch or edit guide settings');
  assert.deepEqual(report.errors, []);
  console.log(JSON.stringify(report, null, 2));
} finally {
  await writeFile(path.join(output, 'ui-results.json'), JSON.stringify(report, null, 2));
  await browser?.close();
  server.kill();
}
