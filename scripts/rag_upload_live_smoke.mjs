/** Opt-in: upload only synthetic documents, index/search/answer through the deployed
 * UI, then delete only the workspace created here. Sends synthetic text to the AI.
 * MEETINGBOT_LIVE_QA=1 node scripts/rag_upload_live_smoke.mjs
 */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

assert.equal(process.env.MEETINGBOT_LIVE_QA, '1', 'Explicitly opt in to the synthetic live AI check');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const { stdout } = await promisify(execFile)('/Applications/Tailscale.app/Contents/MacOS/Tailscale', ['status', '--json']);
const host = JSON.parse(stdout).Self.DNSName.replace(/\.$/, '');
const origin = `https://${host}`;
const key = (await readFile(path.join(root, '.runtime/local-token'), 'utf8')).trim();
const output = path.join(root, '.runtime/rag-upload-viewer-qa');
await mkdir(output, { recursive: true });
const report = { origin, syntheticDocumentsOnly: true, externalDeviceTested: false, checks: [], errors: [] };
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(value => sessionStorage.setItem('stt-token', value), key);
const page = await context.newPage();
page.setDefaultTimeout(15000);
page.on('pageerror', error => report.errors.push(error.name));
const headers = { Authorization: `Bearer ${key}` };
const name = `업로드 뷰어 QA ${Date.now()}`;
let workspaceId;
try {
  assert.equal((await page.goto(origin + '/rag')).status(), 200);
  await page.getByRole('button', { name: '워크스페이스 추가', exact: true }).click();
  await page.getByRole('button', { name: '폴더 선택', exact: true }).click({ trial: true });
  await page.getByLabel('업로드할 폴더', { exact: true }).evaluate(input => {
    const transfer = new DataTransfer();
    for (const [path, content] of [
      ['QA/운영/보관정책.md', '# 업로드 QA 정책\n\n합성 검증 문서입니다.\n\n## 보관 기간\n운영 로그의 보관 기간은 **73일**입니다. 73일 이후 삭제합니다.\n\n| 항목 | 기간 |\n| --- | --- |\n| 운영 로그 | 73일 |'],
      ['QA/운영/제외자료.md', '# 선택 해제 검증\n이 파일은 전송하면 안 됩니다.'],
    ]) {
      const file = new File([content], path.split('/').at(-1), { type: 'text/markdown' });
      Object.defineProperty(file, 'webkitRelativePath', { value: path });
      transfer.items.add(file);
    }
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.getByLabel('이름', { exact: true }).fill(name);
  await page.getByLabel('운영/제외자료.md 업로드 선택', { exact: true }).uncheck();
  const commitResponse = page.waitForResponse(response => /\/api\/rag\/uploads\/[^/]+\/commit$/.test(new URL(response.url()).pathname));
  await page.getByRole('button', { name: '문서 등록', exact: true }).click();
  const commit = await (await commitResponse).json();
  assert.equal(commit.workspace.name, name);
  workspaceId = commit.workspace.id;
  await page.getByRole('button', { name: '워크스페이스 열기', exact: true }).waitFor();
  assert.equal(await page.locator('.rag-upload-files b.completed').count(), 1);
  await page.screenshot({ path: path.join(output, 'live-upload-completed.png'), fullPage: true });
  report.checks.push('Real HTTPS upload sends only checked file and keeps completed status visible');
  let workspace;
  for (let i = 0; i < 60; i++) {
    const response = await context.request.get(`${origin}/api/rag/workspaces/${workspaceId}`, { headers });
    assert.equal(response.status(), 200);
    workspace = await response.json();
    if (workspace.active_revision_id) break;
    if (workspace.latest_job?.state === 'FAILED') throw new Error('Synthetic indexing failed');
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  assert.ok(workspace.active_revision_id, 'Index must become ready');
  assert.equal(workspace.document_count, 1);
  const documents = await (await context.request.get(`${origin}/api/rag/workspaces/${workspaceId}/documents`, { headers })).json();
  assert.deepEqual(documents.files.map(file => file.relative_path), ['운영/보관정책.md']);
  await page.getByRole('button', { name: '워크스페이스 열기', exact: true }).click();
  await page.getByLabel('검색 질문', { exact: true }).fill('운영 로그의 보관 기간은 며칠인가요?');
  const answerResponse = page.waitForResponse(response => new URL(response.url()).pathname === `/api/rag/workspaces/${workspaceId}/questions` && response.request().method() === 'POST', { timeout: 120000 });
  await page.getByRole('button', { name: '질문하기', exact: true }).click();
  const accepted = await answerResponse;
  assert.equal(accepted.status(), 202);
  let answer = await accepted.json();
  const deadline = Date.now() + 180000;
  while (['queued', 'processing'].includes(answer.status) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 1000));
    const saved = await context.request.get(`${origin}/api/rag/history/${answer.request_id}`, { headers });
    assert.equal(saved.status(), 200);
    answer = (await saved.json()).result;
  }
  assert.equal(answer.status, 'answered', answer.reason || 'Expected actual answer');
  assert.match(answer.answer, /73/);
  assert.ok(answer.citations.length);
  assert.equal(answer.llm?.model, 'gpt-5.6-luna');
  await page.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  assert.ok(await page.locator('.rag-evidence-card .rag-markdown').count());
  assert.ok(!/gpt-|외부 전송|AI|LLM|M1|CPU|GPU/.test(await page.locator('body').innerText()));
  await page.getByRole('heading', { name: '문서 기반 답변', exact: true }).waitFor();
  report.checks.push(`Real local indexing and explicit consent produce a cited AI answer (${answer.llm?.model})`);
  await page.getByRole('button', { name: '원문 보기', exact: true }).first().click();
  await page.getByRole('navigation', { name: '문서 목차' }).getByRole('button', { name: '업로드 QA 정책', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown h1').waitFor();
  assert.match(await page.locator('.rag-drawer .rag-markdown').textContent(), /73일/);
  assert.equal(await page.locator('.rag-drawer .rag-markdown table').count(), 1);
  await page.screenshot({ path: path.join(output, 'live-markdown.png'), fullPage: true });
  await page.getByRole('button', { name: '원문 · 줄 번호', exact: true }).click();
  await page.locator('.rag-source-lines .highlight').first().waitFor();
  assert.ok(await page.locator('.rag-source-lines .highlight').count());
  report.checks.push('Real stored Markdown snapshot renders table and toggles back to highlighted source lines');
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: '자료 관리', exact: true }).click();
  await page.getByRole('button', { name: '문서 보기', exact: true }).click();
  await page.locator('.rag-drawer .rag-markdown h1').waitFor();
  report.checks.push('A registered document opens directly from the document list without searching');
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.errors.push(error.message);
  await page.screenshot({ path: path.join(output, 'live-failure.png'), fullPage: true });
  throw error;
} finally {
  if (workspaceId) {
    const found = await (await context.request.get(`${origin}/api/rag/workspaces/${workspaceId}`, { headers })).json();
    assert.equal(found.name, name, 'Only remove this run’s synthetic workspace');
    const removed = await context.request.delete(`${origin}/api/rag/workspaces/${workspaceId}`, { headers });
    assert.equal(removed.status(), 200);
    report.checks.push('Synthetic workspace and uploaded copies removed; existing workspaces unchanged');
  }
  await browser.close();
  await writeFile(path.join(output, 'live-results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
