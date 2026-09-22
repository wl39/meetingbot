/** Verify the deployed workspace through its configured Tailscale HTTPS origin.
 * Uses only this installation's key; no recording, indexing, downloads or saved setting changes.
 * Reports never contain the key, cookie, CSRF value or token-bearing URL.
 */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const executable = process.env.TAILSCALE_BIN || (process.platform === 'darwin' ? '/Applications/Tailscale.app/Contents/MacOS/Tailscale' : 'tailscale');
const { stdout } = await promisify(execFile)(executable, ['status', '--json']);
const status = JSON.parse(stdout);
assert.equal(status.BackendState, 'Running', 'Tailscale must be connected');
const hostname = status.Self.DNSName.replace(/\.$/, '');
assert.match(hostname, /^[a-z0-9-]+\.[a-z0-9.-]+\.ts\.net$/);
const origin = `https://${hostname}`;
const key = (await readFile(process.env.MEETINGBOT_TOKEN_FILE || path.join(root, '.runtime/local-token'), 'utf8')).trim();
const output = path.join(root, '.runtime', 'tailnet-qa');
await mkdir(output, { recursive: true });
const { stdout: serving } = await promisify(execFile)(executable, ['serve', 'status', '--json']);
const serve = JSON.parse(serving);
assert.equal(serve.Web[`${hostname}:443`].Handlers['/'].Proxy, 'http://127.0.0.1:8765');
assert.notEqual(serve.AllowFunnel?.[`${hostname}:443`], true, 'Workspace must stay inside the tailnet');
const report = { origin, checks: [], errors: [], externalDeviceTested: false };
const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
try {
  const guest = await browser.newContext();
  const denied = await guest.request.get(origin + '/api/system');
  assert.equal(denied.status(), 401);
  const guestPage = await guest.newPage();
  await guestPage.goto(origin + '/settings');
  await guestPage.getByLabel('관리 접속 키').waitFor();
  report.checks.push('HTTPS certificate valid, tailnet-only Serve route, guest API denied and login shown');
  await guest.close();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(value => sessionStorage.setItem('stt-token', value), key);
  const page = await context.newPage();
  page.on('pageerror', error => report.errors.push(error.name));
  const apiRequests = [];
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/api/')) apiRequests.push({ origin: url.origin, path: url.pathname }); });
  for (const [route, heading] of [
    ['/settings', '읽기 편한 화면'], ['/settings/speech', '설치와 적용 상태'],
    ['/settings/rag', '문서를 나누고, 근거를 찾는 방식'], ['/settings/ai', '기본 모델과 답변 옵션'],
    ['/settings/updates', '프로그램 업데이트'],
  ]) {
    const response = await page.goto(origin + route);
    assert.equal(response.status(), 200);
    await page.getByText(heading, { exact: true }).waitFor();
    assert.equal(await page.locator('.management-error:visible,.rag-alert:visible').count(), 0, route);
  }
  report.checks.push('All five management pages connect to actual APIs through Tailscale HTTPS');
  assert.ok(apiRequests.length > 10);
  assert.ok(apiRequests.every(request => request.origin === origin), 'Remote browser must never call its own localhost');
  assert.equal(await page.evaluate(() => isSecureContext && typeof navigator.mediaDevices?.getUserMedia === 'function'), true);
  report.checks.push('API requests use the HTTPS origin and browser microphone secure context is available');
  const csrfStatus = await page.evaluate(async () => {
    const session = await (await fetch('/api/rag/auth/session')).json();
    const denied = await fetch('/api/rag/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const validated = await fetch('/api/rag/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf }, body: '{}' });
    return { denied: denied.status, validated: validated.status };
  });
  assert.equal(csrfStatus.denied, 403);
  assert.equal(csrfStatus.validated, 422);
  report.checks.push('RAG cookie/CSRF works behind Serve; invalid requests do not alter settings');
  for (const route of ['/', '/live', '/rag']) {
    assert.equal((await page.goto(origin + route)).status(), 200);
    await page.waitForLoadState('networkidle');
    assert.equal(await page.locator('.error-banner:visible,.rag-alert:visible').count(), 0);
  }
  report.checks.push('Transcription, live and document library routes remain accessible');
  await page.goto(origin + '/settings');
  await page.getByText('읽기 편한 화면', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, 'settings-https.png'), fullPage: true });
  const tailnetIPv4 = status.TailscaleIPs.find(ip => !ip.includes(':'));
  if (tailnetIPv4) {
    const response = await context.request.get(`http://${tailnetIPv4}:8765/settings`, { maxRedirects: 0 });
    assert.equal(response.status(), 307);
    assert.equal(response.headers().location, origin + '/settings');
    report.checks.push('Tailscale IP entry preserves the path when redirecting to HTTPS');
  }
  assert.equal(report.errors.length, 0);
} finally {
  await browser.close();
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
