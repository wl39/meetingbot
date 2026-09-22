/** Real guest upload/create/search flow. Deletes only the workspace it creates. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import path from 'node:path';

const base = process.env.MEETINGBOT_TEST_URL || 'http://127.0.0.1:8765';
const output = path.resolve('.runtime/visitor-workspace-qa', new URL(base).port || 'https');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
const report = { base, checks: [], errors: [] };
let page, wid;
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.message));
  await page.goto(base + '/rag');
  await page.getByRole('heading', { name: '자료 라이브러리', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => sessionStorage.getItem('stt-token')), null);
  await page.getByText('로그인 없이 파일이나 폴더를 올려 내 워크스페이스를 만들 수 있습니다.', { exact: true }).waitFor();
  for (const name of ['워크스페이스 추가', '워크스페이스 만들기', '새 자료 연결']) {
    await page.getByRole('button', { name, exact: name !== '새 자료 연결' }).click();
    await page.getByRole('heading', { name: '문서 등록', exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: '공유 폴더 연결', exact: true }).count(), 0);
    await page.getByRole('button', { name: '라이브러리로 돌아가기', exact: true }).click();
  }
  report.checks.push('All three creation entry points work without login');
  await page.getByRole('button', { name: '워크스페이스 만들기', exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '파일 선택' && !b.disabled));
  await page.getByLabel('업로드할 파일', { exact: true }).setInputFiles({ name: '방문자-검증.md', mimeType: 'text/markdown', buffer: Buffer.from('# 검증용 운영 정책\n\n운영 서버의 로그 보관 기간은 75일입니다.\n') });
  const name = '방문자 워크스페이스 검증 ' + Date.now();
  await page.getByLabel('이름', { exact: true }).fill(name);
  const committed = page.waitForResponse(r => r.url().endsWith('/commit') && r.request().method() === 'POST');
  committed.catch(() => {});
  await page.getByRole('button', { name: '문서 등록', exact: true }).click();
  const response = await committed;
  assert.equal(response.status(), 200);
  const result = await response.json();
  wid = result.workspace.id;
  assert.equal(result.workspace.visibility, 'private');
  assert.equal(result.workspace.can_manage, true);
  await page.getByRole('button', { name: '워크스페이스 열기', exact: true }).click();
  await page.getByLabel('검색 질문', { exact: true }).fill('운영 서버 로그 보관 기간');
  await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent.trim() === '문서 검색' && !b.disabled), null, { timeout: 90000 });
  await page.getByRole('button', { name: '문서 검색', exact: true }).click();
  await page.locator('.rag-evidence-card').filter({ hasText: '75일' }).first().waitFor();
  report.checks.push('Guest file upload creates a private workspace, indexes and searches successfully');
  await page.screenshot({ path: path.join(output, 'guest-search.png'), fullPage: true });
  await page.reload();
  await page.getByRole('button', { name: '자료 라이브러리', exact: true }).click();
  await page.getByRole('button').filter({ has: page.getByRole('heading', { name, exact: true }) }).click();
  await page.getByLabel('검색 질문', { exact: true }).waitFor();
  report.checks.push('Same browser can reopen the workspace after refresh');
  const other = await browser.newPage();
  await other.goto(base + '/rag');
  await other.getByRole('heading', { name: '자료 라이브러리', exact: true }).waitFor();
  assert.equal(await other.evaluate(async id => (await fetch('/api/rag/workspaces/' + id)).status, wid), 404);
  assert.equal(await other.getByText(name, { exact: true }).count(), 0);
  report.checks.push('Another visitor cannot list or open the private workspace');
  await other.close();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '자료 라이브러리', exact: true }).click();
  await page.getByRole('button', { name: '워크스페이스 만들기', exact: true }).click();
  await page.getByRole('heading', { name: '문서 등록', exact: true }).waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: path.join(output, 'guest-create-mobile.png'), fullPage: true });
  report.checks.push('Guest can open creation on mobile without horizontal overflow');
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.errors.push(error.message);
  await page?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  throw error;
} finally {
  try {
    if (wid && page) {
      const status = await page.evaluate(async id => {
        const session = await (await fetch('/api/access/session')).json();
        return (await fetch('/api/rag/workspaces/' + id, { method: 'DELETE', headers: { 'X-CSRF-Token': session.csrf } })).status;
      }, wid);
      assert.equal(status, 200, 'Temporary workspace must be removed');
      report.temporary_workspace_removed = true;
    }
  } finally {
    await writeFile(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    await browser.close();
  }
}
console.log(JSON.stringify(report, null, 2));
