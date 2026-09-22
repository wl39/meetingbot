/**
 * Synthetic integration coverage for microphone -> WAV -> file onboarding.
 * All API, microphone, AudioContext/worklet, and meeting WebSocket traffic uses
 * deterministic fixtures. No real microphone or live service data is accessed.
 * Run against the existing development server: node scripts/onboarding_audio_smoke.mjs
 */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime', 'onboarding-audio-qa');
await mkdir(output, { recursive: true });
const base = process.env.ONBOARDING_AUDIO_QA_URL || 'http://127.0.0.1:5173';
const report = {
  synthetic: true,
  limitations: 'Mock microphone PCM, AudioContext/worklet, WebSocket and API fixtures; no physical recording, speech recognition or live server data changes.',
  checks: [], errors: [], requests: [],
};
const workspace = {
  id: 'c'.repeat(32), name: '음성 체험 문서', description: '음성 튜토리얼 검증용 문서',
  state: 'READY', document_count: 1, active_revision_id: 'audio-revision', consent: 'fixture-provider',
  can_manage: true, visibility: 'private', access_state: 'AVAILABLE',
  source: { kind: 'upload', label: '체험 문서' }, latest_job: null,
};
const diagnostics = {
  model: { state: 'READY' },
  llm: { global_allowed: true, configured: true, provider_id: 'fixture-provider' },
  history_days: 30, limits: {},
};
const utterance = {
  utterance_id: 'audio-utterance', revision: 1, start_ms: 0, end_ms: 1000,
  text: '제품팀 회의는 매주 월요일에 진행합니다.', speaker_id: 'speaker-a',
  status: 'final', speaker_status: 'final', overlap: false, manual_fields: [], words: [],
};
const blankSession = (id, mode) => ({
  id, mode, state: 'CREATED', snapshot_revision: 1, utterances: [], speakers: {},
  warnings: [], metrics: {}, audio_retained: false,
});
const completed = session => ({
  ...session, state: 'COMPLETED', snapshot_revision: session.snapshot_revision + 1,
  utterances: [utterance], speakers: { 'speaker-a': '발언자 A' }, metrics: { processed_audio_ms: 1000 },
});
let browser, currentPage;

async function fixturePage(scenario) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(12000);
  page.on('pageerror', error => report.errors.push(`${scenario}: ${error.message}`));
  const sessions = new Map();
  const fixture = { page, sessions, scenario, liveCreates: 0, fileCreates: 0, finishCalls: 0,
    receivedChunks: new Map(), uploadedSize: 0, fileFinalized: false, holdFileCompletion: true, wav: null,
    deletedIds: [] };
  await page.addInitScript(({ workspace, scenario }) => {
    localStorage.setItem(`meetingbot:getting-started:v1:audio-${scenario}`, JSON.stringify({
      step: 'voice', source: 'own', workspaceId: workspace.id, workspaceName: workspace.name,
      query: '제품팀 회의는 언제인가요?', voicePrompt: '제품팀 회의는 매주 월요일에 진행합니다.',
      searched: true, recorded: false, uploaded: false,
    }));
    const audio = window.__audioFixture = {
      socket: null, node: null, frames: [], mediaCalls: 0, stoppedTracks: 0, contextCloses: 0,
      stop: null, connection: null, workletUrl: null,
      emit(samples) {
        if (!this.node?.port.onmessage) throw new Error('Worklet message listener not ready');
        this.node.port.onmessage({ data: { type: 'audio', samples: new Float32Array(samples) } });
      },
      finish(session) {
        if (!this.stop) throw new Error('Client must flush and stop before completion');
        this.socket.receive({ type: 'snapshot', session });
        this.socket.receive({ type: 'completed' });
      },
    };
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: async options => {
      if (!options.audio || options.video !== false) throw new Error('Unexpected microphone constraints');
      audio.mediaCalls++;
      return { getTracks: () => [{ stop: () => audio.stoppedTracks++ }] };
    } });
    class FixtureContext {
      sampleRate = 48000;
      destination = {};
      audioWorklet = { addModule: async url => { audio.workletUrl = url; } };
      resume() { return Promise.resolve(); }
      suspend() { return Promise.resolve(); }
      close() { audio.contextCloses++; return Promise.resolve(); }
      createMediaStreamSource() { return { connect() {} }; }
    }
    class FixtureWorklet {
      constructor(context, name) {
        if (name !== 'pcm-collector') throw new Error('Unexpected worklet');
        this.port = {
          onmessage: null,
          postMessage: command => {
            if (command !== 'stop') throw new Error('Unexpected worklet message');
            queueMicrotask(() => {
              // A final partial frame verifies that stop includes the flushed tail.
              this.port.onmessage?.({ data: { type: 'audio', samples: new Float32Array([0.25, 0.25, 0.25]) } });
              this.port.onmessage?.({ data: { type: 'flushed' } });
            });
          },
        };
        audio.node = this;
      }
      connect() {}
      disconnect() {}
    }
    class FixtureSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;
      readyState = 0;
      bufferedAmount = 0;
      constructor(url, protocols) {
        // Keep concurrent development HMR from reloading a fixture mid-test.
        // This socket intentionally connects only to the in-page fixture.
        this.isAudio = String(url).includes('/api/stt/sessions/');
        if (this.isAudio) audio.socket = this;
        setTimeout(() => { this.readyState = 1; this.onopen?.({}); }, 0);
      }
      receive(message) { this.onmessage?.({ data: JSON.stringify(message) }); }
      send(message) {
        if (!this.isAudio) return;
        if (typeof message === 'string') {
          const command = JSON.parse(message);
          if (command.type === 'start') {
            audio.connection = command;
            queueMicrotask(() => this.receive({ type: 'ack', action: 'start' }));
          } else if (command.type === 'stop') audio.stop = command;
          else throw new Error('Unexpected socket command');
          return;
        }
        const view = new DataView(message);
        audio.frames.push({ sequence: view.getUint32(0, true), start: Number(view.getBigUint64(4, true)),
          samples: view.getUint32(12, true), size: message.byteLength });
      }
      close() { this.readyState = 3; queueMicrotask(() => this.onclose?.({})); }
    }
    window.AudioContext = FixtureContext;
    window.AudioWorkletNode = FixtureWorklet;
    window.WebSocket = FixtureSocket;
  }, { workspace, scenario });
  await page.route('**/api/**', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname, method = request.method();
    report.requests.push({ scenario, path: pathname, method });
    try {
      let data;
      if (pathname === '/api/access/session') data = {
        authenticated: true, role: 'visitor', account: { id: `audio-${scenario}`, label: '음성 체험 사용자', role: 'visitor' },
        keyless: true, demo: false, csrf: 'fixture-csrf', limits: { seconds: 300, file_mb: 30, jobs_per_visitor: 5, jobs_daily: 50 },
      };
      else if (pathname === '/api/system/theme') data = { color: '#b85c12' };
      else if (pathname === '/api/events') data = {};
      else if (pathname === '/api/rag/auth/session') data = { csrf: 'fixture-csrf' };
      else if (pathname === '/api/stt/health') data = {
        engine: 'real', default_model: 'small', active_session: null, management_busy: false,
        limits: { file_mb: 30, file_seconds: 300, live_seconds: 300 }, environment: { machine: 'fixture', system: 'fixture' },
        workers: { asr: { ready: true }, diar: { ready: true }, vad: { ready: true } },
      };
      else if (pathname === '/api/stt/meeting/workspaces' || pathname === '/api/rag/workspaces') data = [workspace];
      else if (pathname === '/api/stt/meeting/diagnostics' || pathname === '/api/rag/diagnostics') data = diagnostics;
      else if (pathname === '/api/stt/sessions' && method === 'GET') data = [...sessions.values()].map(item => ({
        id: item.id, mode: item.mode, state: item.state, created_at: 1789000000,
      }));
      else if (pathname === '/api/stt/sessions' && method === 'POST') {
        fixture.liveCreates++;
        assert.equal(request.postDataJSON().language, 'ko');
        data = blankSession(`live-${scenario}`, 'microphone');
        sessions.set(data.id, data);
      }
      else if (/^\/api\/stt\/sessions\/[^/]+$/.test(pathname) && method === 'DELETE') {
        const id = pathname.split('/').at(-1);
        assert(sessions.has(id), `deleting known fixture session ${id}`);
        sessions.delete(id);
        fixture.deletedIds.push(id);
        await route.fulfill({ status: 204 });
        return;
      }
      else if (/^\/api\/stt\/sessions\/[^/]+$/.test(pathname) && method === 'GET') {
        const id = pathname.split('/').at(-1);
        data = sessions.get(id);
        if (!data) {
          await route.fulfill({ status: 404, json: { detail: 'NOT_FOUND' } });
          return;
        }
        if (id === `file-${scenario}` && fixture.fileFinalized && !fixture.holdFileCompletion) {
          data = data.state === 'COMPLETED' ? data : completed(data);
          sessions.set(id, data);
        }
      }
      else if (pathname.endsWith('/subscription') && method === 'GET') data = { enabled: false, workspace_id: null, revision_id: null };
      else if (pathname.endsWith('/jobs')) data = { jobs: [], total: 0, next_cursor: null,
        scheduler: { mode: 'NORMAL', pq_pending: 0, sq_pending: 0, filter_pending: 0, oldest_sq_seconds: 0 }, policy: {} };
      else if (pathname === '/api/stt/files/stream' && method === 'POST') {
        fixture.fileCreates++;
        const metadata = request.postDataJSON();
        assert.equal(metadata.filename, '내 첫 음성 테스트.wav');
        assert(metadata.size > 44);
        fixture.uploadedSize = metadata.size;
        sessions.set(`file-${scenario}`, { ...blankSession(`file-${scenario}`, 'file'), state: 'UPLOADING',
          source_file: { name: metadata.filename, size: metadata.size } });
        data = { session_id: `file-${scenario}`, chunk_bytes: 4096 };
      }
      else if (pathname.includes(`/files/file-${scenario}/chunks/`) && method === 'PUT') {
        const index = Number(pathname.split('/').at(-1));
        assert.equal(request.headers()['content-type'], 'application/octet-stream');
        assert(!fixture.receivedChunks.has(index), 'each chunk is uploaded once');
        fixture.receivedChunks.set(index, request.postDataBuffer());
        data = {};
      }
      else if (pathname === `/api/stt/files/file-${scenario}/finish` && method === 'POST') {
        fixture.finishCalls++;
        const bytes = Buffer.concat([...fixture.receivedChunks.entries()].sort(([a], [b]) => a - b).map(([, chunk]) => chunk));
        assert.equal(bytes.length, fixture.uploadedSize, 'full WAV uploaded');
        assert.equal(bytes.subarray(0, 4).toString(), 'RIFF');
        assert.equal(bytes.subarray(8, 12).toString(), 'WAVE');
        assert.equal(bytes.readUInt32LE(4), bytes.length - 8);
        assert.equal(bytes.readUInt32LE(24), 16000);
        assert.equal(bytes.readUInt16LE(22), 1);
        assert.equal(bytes.readUInt16LE(34), 16);
        assert.equal(bytes.readUInt32LE(40), bytes.length - 44);
        // The final worklet tail must survive capture cleanup, conversion and upload.
        assert.equal(bytes.readInt16LE(bytes.length - 2), 8192);
        fixture.wav = { bytes: bytes.length, frames: (bytes.length - 44) / 2, sampleRate: 16000,
          uploadedChunks: fixture.receivedChunks.size, tailSample: bytes.readInt16LE(bytes.length - 2) };
        fixture.fileFinalized = true;
        sessions.set(`file-${scenario}`, { ...sessions.get(`file-${scenario}`), state: 'TRANSCRIBING', snapshot_revision: 2 });
        data = {};
      }
      else throw new Error(`Unexpected fixture request: ${method} ${pathname}`);
      await route.fulfill({ json: data }).catch(() => {});
    } catch (error) {
      report.errors.push(`${scenario}: ${error.message}`);
      await route.fulfill({ status: 500, json: { detail: '브라우저 검증 응답 오류' } }).catch(() => {});
    }
  });
  return fixture;
}

async function awaitEnabled(locator) {
  await locator.waitFor();
  await locator.evaluate(element => new Promise((resolve, reject) => {
    const started = Date.now();
    const poll = () => {
      if (!element.disabled) resolve();
      else if (Date.now() - started > 10000) reject(new Error(`Button remained disabled: ${element.textContent}`));
      else requestAnimationFrame(poll);
    };
    poll();
  }));
}

try {
  assert((await fetch(base)).ok, `existing development server available at ${base}`);
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const success = await fixturePage('success');
  const page = currentPage = success.page;
  await page.goto(base + '/live');
  await page.getByRole('heading', { name: '이번에는 직접 말해보세요', exact: true }).waitFor();
  await page.waitForFunction(id => document.querySelector('#meeting-workspace')?.value === id, workspace.id);
  await page.evaluate(() => new Promise(resolve => {
    scrollTo(0, 0);
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
  await page.screenshot({ path: path.join(output, 'voice-before-recording.png'), fullPage: true });
  report.initialLayout = await page.evaluate(() => ({
    sidebar: document.querySelector('.sidebar')?.getBoundingClientRect().toJSON(),
    guide: document.querySelector('[aria-label="시작 가이드"]')?.getBoundingClientRect().toJSON(),
  }));
  const nextFile = page.getByRole('button', { name: '파일로 이어서', exact: true });
  const start = page.getByRole('button', { name: '녹음 시작', exact: true });
  await awaitEnabled(start);
  assert(await nextFile.isDisabled(), 'opening voice step does not count as recording');
  await start.click();
  await page.getByRole('button', { name: '녹음 중지', exact: true }).waitFor();
  assert.equal(success.liveCreates, 1, 'one actual UI session creation');
  assert(await page.locator('.record-page-delete').isDisabled(), 'active recording must stop before deletion');
  assert(await page.locator('.transcript-footer .danger-text').isDisabled(), 'footer deletion is disabled during recording');
  await page.evaluate(() => {
    // Three chunks of known synthetic microphone PCM, exactly one second.
    for (let chunk = 0; chunk < 3; chunk++) {
      const samples = Array.from({ length: 16000 }, (_, index) => Math.sin((chunk * 16000 + index) * Math.PI / 80) * 0.5);
      window.__audioFixture.emit(samples);
    }
  });
  assert(await nextFile.isDisabled(), 'PCM capture alone does not unlock completion');
  await page.getByRole('button', { name: '녹음 중지', exact: true }).click();
  await page.waitForFunction(() => !!window.__audioFixture.stop);
  assert(await nextFile.isDisabled(), 'waiting for the final transcript does not unlock file step');
  const frames = await page.evaluate(() => ({ frames: window.__audioFixture.frames, stop: window.__audioFixture.stop,
    mediaCalls: window.__audioFixture.mediaCalls, connection: window.__audioFixture.connection }));
  assert.equal(frames.frames.length, 4, 'three PCM chunks plus the flushed tail');
  assert.deepEqual(frames.frames.map(frame => frame.sequence), [0, 1, 2, 3]);
  assert.deepEqual(frames.frames.map(frame => frame.start), [0, 16000, 32000, 48000]);
  assert.equal(frames.stop.last_sequence, 3);
  assert.equal(frames.mediaCalls, 1);
  assert.equal(frames.connection.sample_rate, 48000);
  const liveDone = completed(success.sessions.get('live-success'));
  success.sessions.set(liveDone.id, liveDone);
  await page.evaluate(session => window.__audioFixture.finish(session), liveDone);
  await awaitEnabled(nextFile);
  await page.getByText('음성 기록을 만들었어요', { exact: true }).waitFor();
  await page.getByText(utterance.text, { exact: true }).first().waitFor();
  // Continue immediately after the enabled transition: capture cleanup must
  // already have supplied the WAV, without relying on a later polling tick.
  await nextFile.click();
  await page.getByRole('heading', { name: '방금 녹음한 음성을 파일로 올려보세요', exact: true }).waitFor();
  assert.equal(await page.getByText(utterance.text, { exact: true }).count(), 0, 'old live session is cleared on file navigation');
  const finish = page.getByRole('button', { name: '체험 마치기', exact: true });
  assert(await finish.isDisabled(), 'live success does not count as file success');
  const reused = page.getByRole('button', { name: '방금 녹음한 음성 사용', exact: true });
  await reused.click();
  await page.getByRole('button', { name: /내 첫 음성 테스트.wav/ }).waitFor();
  const upload = page.getByRole('button', { name: '업로드 및 전사 시작', exact: true });
  await awaitEnabled(upload);
  await upload.click();
  await page.waitForFunction(() => document.body.innerText.includes('음성을 텍스트로 변환 중'));
  assert.equal(success.fileCreates, 1);
  assert.equal(success.finishCalls, 1);
  assert(success.receivedChunks.size > 1, 'reused recording follows the multipart upload path');
  assert(await finish.isDisabled(), 'upload completion without a final transcript does not finish tutorial');
  success.holdFileCompletion = false;
  await awaitEnabled(finish);
  await page.getByText('파일로 대본을 만들었어요', { exact: true }).waitFor();
  await page.getByText(utterance.text, { exact: true }).first().waitFor();
  await page.evaluate(() => new Promise(resolve => {
    scrollTo(0, 0);
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  }));
  await page.screenshot({ path: path.join(output, 'reused-recording-complete.png'), fullPage: true });
  const state = await page.evaluate(() => JSON.parse(localStorage.getItem('meetingbot:getting-started:v1:audio-success')));
  assert.equal(state.recorded, true);
  assert.equal(state.uploaded, true);
  assert.equal(state.step, 'file');
  const cleanup = await page.evaluate(() => ({ stoppedTracks: window.__audioFixture.stoppedTracks, contextCloses: window.__audioFixture.contextCloses }));
  assert(cleanup.stoppedTracks >= 1 && cleanup.contextCloses >= 1, 'capture resources were released');
  await finish.click();
  await page.getByRole('heading', { name: '이제 내 회의에 활용해 보세요', exact: true }).waitFor();
  report.checks.push('Completed live transcript unlocks the file step and supplies reusable WAV before immediate navigation');
  report.checks.push('App clears the live session on file navigation and does not reuse it as file completion');
  report.checks.push('Recorded PCM including the final worklet tail becomes a valid 16 kHz mono WAV, selected via the reuse button and uploaded in chunks');
  report.checks.push('File step remains incomplete during upload/processing and unlocks Finish only after a terminal nonempty transcript');
  report.wav = success.wav;
  report.capture = { ...frames, ...cleanup };

  const empty = await fixturePage('empty-transcript');
  currentPage = empty.page;
  await empty.page.goto(base + '/live');
  const emptyStart = empty.page.getByRole('button', { name: '녹음 시작', exact: true });
  await awaitEnabled(emptyStart);
  await emptyStart.click();
  await empty.page.getByRole('button', { name: '녹음 중지', exact: true }).waitFor();
  await empty.page.evaluate(() => window.__audioFixture.emit([0, 0, 0, 0, 0, 0]));
  await empty.page.getByRole('button', { name: '녹음 중지', exact: true }).click();
  await empty.page.waitForFunction(() => !!window.__audioFixture.stop);
  const emptyDone = { ...empty.sessions.get('live-empty-transcript'), state: 'COMPLETED', snapshot_revision: 2 };
  empty.sessions.set(emptyDone.id, emptyDone);
  await empty.page.evaluate(session => window.__audioFixture.finish(session), emptyDone);
  await awaitEnabled(emptyStart);
  assert(await empty.page.getByRole('button', { name: '파일로 이어서', exact: true }).isDisabled(), 'terminal session without recognized words must not count as successful voice test');
  const emptyState = await empty.page.evaluate(() => JSON.parse(localStorage.getItem('meetingbot:getting-started:v1:audio-empty-transcript')));
  assert.equal(emptyState.recorded, false);
  report.checks.push('A completed recording with no recognized transcript remains incomplete and can be retried');

  const deleted = await fixturePage('deleted-recording');
  currentPage = deleted.page;
  await deleted.page.goto(base + '/live');
  const deleteStart = deleted.page.getByRole('button', { name: '녹음 시작', exact: true });
  await awaitEnabled(deleteStart);
  await deleteStart.click();
  await deleted.page.getByRole('button', { name: '녹음 중지', exact: true }).waitFor();
  await deleted.page.evaluate(() => window.__audioFixture.emit(Array.from({ length: 4800 }, (_, i) => Math.sin(i / 80) * 0.5)));
  await deleted.page.getByRole('button', { name: '녹음 중지', exact: true }).click();
  await deleted.page.waitForFunction(() => !!window.__audioFixture.stop);
  const deletedDone = completed(deleted.sessions.get('live-deleted-recording'));
  deleted.sessions.set(deletedDone.id, deletedDone);
  await deleted.page.evaluate(session => window.__audioFixture.finish(session), deletedDone);
  const deleteNext = deleted.page.getByRole('button', { name: '파일로 이어서', exact: true });
  await awaitEnabled(deleteNext);
  // A second record proves clearing is scoped to the recording which supplied
  // the reusable WAV, not every microphone record the user happens to delete.
  deleted.sessions.set('unrelated-recording', completed(blankSession('unrelated-recording', 'microphone')));
  await deleteNext.click();
  const deletionReuse = deleted.page.getByRole('button', { name: '방금 녹음한 음성 사용', exact: true });
  await deletionReuse.click();
  await deleted.page.getByRole('button', { name: /내 첫 음성 테스트.wav/ }).waitFor();
  await deleted.page.waitForFunction(() => document.querySelectorAll('.sidebar .record-item').length === 2);
  await deleted.page.locator('.sidebar .record-item').last().locator('.record-delete').click();
  await deleted.page.locator('.record-confirm-delete').click();
  await deleted.page.locator('.record-confirm-dialog').waitFor({ state: 'detached' });
  assert.deepEqual(deleted.deletedIds, ['unrelated-recording']);
  assert(await deletionReuse.isVisible(), 'deleting another microphone record preserves the tutorial recording');
  assert.equal(await deleted.page.getByRole('button', { name: /내 첫 음성 테스트.wav/ }).count(), 1);
  await deleted.page.locator('.sidebar .record-item').first().locator('.record-delete').click();
  await deleted.page.locator('.record-confirm-delete').click();
  await deleted.page.locator('.record-confirm-dialog').waitFor({ state: 'detached' });
  assert.deepEqual(deleted.deletedIds, ['unrelated-recording', 'live-deleted-recording']);
  await deleted.page.getByRole('heading', { name: '녹음 파일도 같은 방법으로 확인하세요', exact: true }).waitFor();
  assert.equal(await deletionReuse.count(), 0, 'deleted microphone audio cannot be reused by the file tutorial');
  assert.equal(await deleted.page.getByRole('button', { name: /내 첫 음성 테스트.wav/ }).count(), 0, 'an unuploaded selection of the deleted recording is also released');
  assert(await deleted.page.getByRole('button', { name: '업로드 및 전사 시작', exact: true }).isDisabled());
  assert.equal(deleted.fileCreates, 0);
  await deleted.page.screenshot({ path: path.join(output, 'deleted-recording-file-step.png'), fullPage: true });
  report.checks.push('Deleting another microphone record preserves the reusable tutorial audio');
  report.checks.push('Deleting the source recording clears the tutorial WAV, reuse button and unuploaded file selection');
  assert.deepEqual(report.errors, []);
} catch (error) {
  report.failure = error.stack || String(error);
  await currentPage?.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await browser?.close();
  await writeFile(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
}
console.log(JSON.stringify(report, null, 2));
