/** Uses the local UI, but intercepts ALL Codex account APIs with synthetic data. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { readFile, mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

const origin = process.env.PROXY_QA_URL || 'http://127.0.0.1:8765';
const key = (await readFile(new URL('../.runtime/local-token', import.meta.url), 'utf8')).trim();
const browser = await chromium.launch({ headless: true, executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(value => sessionStorage.setItem('stt-token', value), key);
  const accounts = [
    { id: '1'.repeat(64), email: 'firs***@ex***st', status: 'active', enabled: true, manageable: true },
    { id: '2'.repeat(64), email: 'seco***@ex***st', status: 'active', enabled: true, manageable: true },
  ];
  const calls = [];
  let revision = 1, rejectNext = false, loginStatus = null;
  const status = () => {
    const enabled = accounts.filter(item => item.enabled);
    return { installed: true, connected: !!enabled.length, accounts, enabled_count: enabled.length,
      account_count: enabled.length, selected_account_id: enabled.length === 1 ? enabled[0].id : null,
      revision: revision.toString(16).padStart(64, '0'), login_status: loginStatus };
  };
  await context.route('**/api/rag/llm/codex/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/status')) return route.fulfill({ json: status() });
    if (path.endsWith('/login')) {
      loginStatus = 'wait';
      return route.fulfill({ json: { url: 'https://auth.openai.com/oauth/authorize?state=synthetic' } });
    }
    assert.ok(path.endsWith('/accounts/select') || path.endsWith('/accounts/delete'), 'Unexpected account operation');
    const body = route.request().postDataJSON();
    assert.equal(body.expected_revision, status().revision);
    calls.push(path);
    if (rejectNext) {
      rejectNext = false;
      return route.fulfill({ status: 409, json: { error_code: 'CODEX_ACCOUNTS_CHANGED', message: '계정 목록이 변경됐습니다. 상태 확인 후 다시 시도하세요.' } });
    }
    const target = accounts.find(item => item.id === body.account_id);
    assert.ok(target);
    if (path.endsWith('/select')) {
      accounts.forEach(item => { item.enabled = item === target; item.status = item.enabled ? 'active' : 'disabled'; });
    } else accounts.splice(accounts.indexOf(target), 1);
    revision++;
    return route.fulfill({ json: status() });
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(origin + '/settings/ai');
  const list = page.getByRole('list', { name: 'CLIProxyAPI 연결 계정' });
  const row = email => list.getByRole('listitem').filter({ hasText: email });
  await list.waitFor();
  assert.equal(await list.getByRole('button', { name: '이 계정 사용', exact: true }).count(), 2);
  await row(accounts[0].email).getByRole('button', { name: '이 계정 사용', exact: true }).click();
  await row('firs***@ex***st').getByText('선택된 계정', { exact: true }).waitFor();
  await row('seco***@ex***st').getByRole('button', { name: '이 계정 사용', exact: true }).click();
  await row('seco***@ex***st').getByText('선택된 계정', { exact: true }).waitFor();
  rejectNext = true;
  await row('firs***@ex***st').getByRole('button', { name: '이 계정 사용', exact: true }).click();
  const conflict = page.getByRole('alert').filter({ hasText: '계정 목록이 변경됐습니다. 상태 확인 후 다시 시도하세요.' });
  await conflict.waitFor();
  assert.equal(await row('seco***@ex***st').getByText('선택된 계정', { exact: true }).count(), 1);
  await conflict.getByRole('button', { name: '닫기', exact: true }).click();
  await row('seco***@ex***st').getByRole('button', { name: 'seco***@ex***st 연결 삭제', exact: true }).click();
  const confirmation = page.getByRole('group', { name: '계정 삭제 확인' });
  await confirmation.waitFor();
  assert.equal(calls.filter(path => path.endsWith('/delete')).length, 0);
  await confirmation.getByRole('button', { name: '취소', exact: true }).click();
  assert.equal(calls.filter(path => path.endsWith('/delete')).length, 0);
  const output = new URL('../output/proxy-account-ui/', import.meta.url);
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: new URL('desktop.png', output).pathname, fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await list.scrollIntoViewIfNeeded();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.screenshot({ path: new URL('mobile.png', output).pathname, fullPage: true });
  await row('seco***@ex***st').getByRole('button', { name: 'seco***@ex***st 연결 삭제', exact: true }).click();
  await confirmation.getByRole('button', { name: '연결 삭제', exact: true }).click();
  await row('seco***@ex***st').waitFor({ state: 'detached' });
  await row('firs***@ex***st').getByRole('button', { name: 'firs***@ex***st 연결 삭제', exact: true }).click();
  await confirmation.getByRole('button', { name: '연결 삭제', exact: true }).click();
  await page.getByText('등록된 계정이 없습니다. ChatGPT 계정으로 로그인해 연결하세요.', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Codex 로그인', exact: true }).click();
  await page.getByRole('link', { name: 'OpenAI 로그인 창 열기' }).waitFor();
  assert.deepEqual(errors, []);
  assert.equal(calls.filter(path => path.endsWith('/delete')).length, 2);
  console.log('PASS: selection, switching, failure recovery, deletion confirmation/cancel, empty state, login link, desktop/mobile layout. All account mutations were mocked.');
} finally { await browser.close(); }
