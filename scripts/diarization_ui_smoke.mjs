import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
const root = new URL('../', import.meta.url).pathname;
const out = root + '.runtime/diarization-qa';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5179', '--strictPort'], {cwd: root+'frontend', stdio:'ignore'});
let browser;
try {
  for(let i=0;i<40;i++) {try {await fetch('http://127.0.0.1:5179');break;}catch {await new Promise(r=>setTimeout(r,150));}}
  await mkdir(out,{recursive:true});
  browser = await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:1100}});
  const errors=[];page.on('pageerror', e=>errors.push(String(e)));
  await page.addInitScript(()=>sessionStorage.setItem('stt-token','synthetic'));
  const session={id:'synthetic-progress',snapshot_revision:1,mode:'file',state:'DIARIZING',utterances:[],speakers:{},warnings:[],audio_retained:false,source_file:{name:'진행률 확인용 회의.m4a',size:100},metrics:{diar_stage:2,diar_total:1729,diar_completed:864,diar_device:1,diar_started_at:Date.now()/1000-90}};
  await page.route('**/api/**',async route=>{
    const p=new URL(route.request().url()).pathname;
    const data=p.endsWith('/health')?{engine:'fake',active_session:session.id,limits:{file_mb:4096,file_seconds:18000},workers:{asr:{ready:true},diar:{ready:true}},environment:{machine:'synthetic'}}:p==='/api/stt/sessions'?[{id:session.id,mode:'file',state:session.state,created_at:1770000000}]:p===`/api/stt/sessions/${session.id}`?session:{};
    await route.fulfill({json:data});
  });
  await page.goto('http://127.0.0.1:5179');
  await page.locator('.history button').click();
  const panel=page.getByLabel('화자 분석 진행 상황');
  await panel.waitFor();
  assert.match(await panel.innerText(),/목소리 특징 추출 · 50%/);
  assert.match(await panel.innerText(),/Mac GPU · MPS/);
  assert.equal(await panel.getByRole('progressbar').getAttribute('value'),'50');
  await panel.screenshot({path:out+'/desktop.png'});
  await page.setViewportSize({width:390,height:900});
  await panel.screenshot({path:out+'/mobile.png'});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  session.metrics={diar_stage:3,diar_total:0,diar_completed:0,diar_device:1};session.snapshot_revision++;
  await page.waitForFunction(()=>document.querySelector('.diarization-progress-heading')?.textContent.includes('같은 화자 묶기'));
  assert.equal(await panel.getByRole('progressbar').getAttribute('value'),null);
  session.metrics={diar_stage:1,diar_total:10,diar_completed:1,diar_device:0,diar_cpu_fallback:1};session.snapshot_revision++;
  await page.waitForFunction(()=>document.querySelector('.diarization-fallback'));
  assert.match(await panel.innerText(),/CPU로 화자 분석을 다시/);
  assert.deepEqual(errors,[]);
  console.log('PASS: live progress updates, GPU badge, indeterminate clustering, CPU fallback, desktop/mobile layout');
} finally {await browser?.close();server.kill();}
