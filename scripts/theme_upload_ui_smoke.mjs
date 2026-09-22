import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import os from 'node:os';
import path from 'node:path';

// Start a local demo first; set MEETINGBOT_TEST_URL to test another installation.
const base = process.env.MEETINGBOT_TEST_URL || 'http://127.0.0.1:8875';
const key = (await readFile(process.env.MEETINGBOT_TEST_KEY_FILE || path.join(os.homedir(), 'Library/Application Support/MeetingbotDemo/stt/local-token'), 'utf8')).trim();
const output = path.resolve('output/theme-upload-qa');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
const report = { checks: [], errors: [] };
let wid;
let visitor;
let administrator;
try {
  const adminContext = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await adminContext.addInitScript((credential) => sessionStorage.setItem('stt-token', credential), key);
  administrator = await adminContext.newPage();
  administrator.on('pageerror', (e) => report.errors.push(e.message));
  await administrator.goto(base + '/settings');
  await administrator.getByRole('heading', { name: '전체 테마색', exact: true }).waitFor();
  await administrator.getByRole('button', { name: '오션 블루', exact: true }).click();
  await administrator.getByRole('button', { name: '전체 화면에 적용', exact: true }).click();
  await administrator.getByText('전체 테마색을 저장했습니다. 방문자 화면에도 적용됩니다.', { exact: true }).waitFor();

  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  visitor = await context.newPage();
  visitor.on('pageerror', (e) => report.errors.push(e.message));
  await visitor.goto(base + '/rag');
  await visitor.waitForFunction(() => document.documentElement.style.getPropertyValue('--theme-primary') === '#2563eb');
  report.checks.push('Saved theme is applied in a separate visitor browser');
  await administrator.getByRole('button', { name: '서재 오렌지', exact: true }).click();
  await administrator.getByRole('button', { name: '전체 화면에 적용', exact: true }).click();
  await administrator.getByText('전체 테마색을 저장했습니다. 방문자 화면에도 적용됩니다.', { exact: true }).waitFor();
  await visitor.waitForFunction(() => document.documentElement.style.getPropertyValue('--theme-primary') === '#b85c12', null, { timeout: 25000 });
  report.checks.push('Open visitor page receives orange theme without reload');
  await administrator.locator('.theme-settings').scrollIntoViewIfNeeded();
  await administrator.screenshot({ path: path.join(output, 'theme-settings.png'), fullPage: true });
  await visitor.getByRole('button', { name: '워크스페이스 만들기', exact: true }).click();
  assert.equal(await visitor.getByRole('button', { name: '공유 폴더 연결', exact: true }).count(), 0);
  await visitor.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === '파일 선택' && !b.disabled));
  await visitor.getByLabel('업로드할 파일', { exact: true }).setInputFiles({ name: '방문자-검증.md', mimeType: 'text/markdown', buffer: Buffer.from('# 회의봇 검증 자료\n\n검증용 운영 서버의 로그 보관 기간은 75일입니다.\n') });
  await visitor.getByLabel('이름', { exact: true }).fill('방문자 업로드 UI 검증');
  const committed = visitor.waitForResponse((r) => r.url().endsWith('/commit') && r.request().method() === 'POST');
  committed.catch(() => {});
  await visitor.getByRole('button', { name: '문서 등록', exact: true }).click();
  const response = await committed;
  assert.equal(response.status(), 200);
  const result = await response.json();
  wid = result.workspace.id;
  assert.equal(result.workspace.visibility, 'private');
  await visitor.getByRole('button', { name: '워크스페이스 열기', exact: true }).click();
  await visitor.getByLabel('검색 질문', { exact: true }).fill('운영 서버 로그 보관 기간');
  await visitor.waitForFunction(() => [...document.querySelectorAll('button')].some((b) => b.textContent.trim() === '문서 검색' && !b.disabled), null, { timeout: 90000 });
  await visitor.getByRole('button', { name: '문서 검색', exact: true }).click();
  await visitor.locator('.rag-evidence-card').filter({ hasText: '75일' }).first().waitFor();
  report.checks.push('Guest file upload, automatic indexing and real document search');
  await visitor.screenshot({ path: path.join(output, 'visitor-search.png'), fullPage: true });
  const otherContext = await browser.newContext();
  const other = await otherContext.newPage();
  await other.goto(base + '/rag');
  await other.getByRole('button', { name: '워크스페이스 만들기', exact: true }).waitFor();
  assert.equal(await other.evaluate(async (id) => (await fetch('/api/rag/workspaces/' + id)).status, wid), 404);
  assert.equal(await other.getByText('방문자 업로드 UI 검증', { exact: true }).count(), 0);
  report.checks.push('Other visitor cannot list or open uploaded workspace');
  await visitor.setViewportSize({ width: 390, height: 844 });
  await visitor.screenshot({ path: path.join(output, 'visitor-mobile.png'), fullPage: true });
  assert.equal(await visitor.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await administrator.setViewportSize({ width: 390, height: 844 });
  await administrator.locator('.theme-settings').scrollIntoViewIfNeeded();
  assert.equal(await administrator.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  report.checks.push('Visitor and theme settings layouts fit mobile viewport');
  assert.deepEqual(report.errors, []);
} catch (error) {
  if (visitor) {
    await visitor.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
    report.errors.push(await visitor.locator('[role="alert"]').allTextContents());
  }
  report.errors.push(error.message);
  throw error;
} finally {
  if (administrator) await administrator.evaluate(async () => {
    await fetch('/api/system/theme', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + sessionStorage.getItem('stt-token') }, body: JSON.stringify({ color: '#b85c12' }) });
  }).catch(() => {});
  if (wid && visitor) await visitor.evaluate(async (id) => {
    const session = await (await fetch('/api/access/session')).json();
    const result = await fetch('/api/rag/workspaces/' + id, { method: 'DELETE', headers: { 'X-CSRF-Token': session.csrf } });
    if (!result.ok) throw new Error('Could not delete QA workspace');
  }, wid);
  await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
console.log(JSON.stringify(report, null, 2));
