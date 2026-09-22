import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.runtime', 'management-qa');
await mkdir(output, { recursive: true });
const port = 5193, base = `http://127.0.0.1:${port}`;
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', String(port), '--strictPort'], { cwd: path.join(root, 'frontend'), stdio: 'ignore' });
let browser;
const report = { synthetic: true, checks: [], errors: [], requests: [] };
try {
  for (let i=0;i<60;i++) { try { await fetch(base); break; } catch { await new Promise(r=>setTimeout(r,100)); } }
  browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(10000);
  page.on('pageerror', e=>report.errors.push(e.message));
  await page.addInitScript(()=>{
    sessionStorage.setItem('stt-token','synthetic');
    window.__clipboardWrites=[];
    window.__clipboardReject=false;
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{
      if(window.__clipboardReject) throw new Error('Synthetic clipboard rejection');
      window.__clipboardWrites.push(value);
    }}});
  });
  const status = {
    platform:{os:'Darwin',machine:'arm64',python:'3.12.11'}, selection:{engine:'mlx',model:'small'},
    engines:[{id:'mlx',name:'MLX Whisper',supported:true,installed:true},{id:'faster-whisper',name:'Faster Whisper',supported:true,installed:false}],
    models:['mlx','faster-whisper'].flatMap(engine=>['small','large-v3-turbo'].map(model=>({id:`${engine}:${model}`,engine,model,name:model,supported:true,installed:engine==='mlx'||model==='small',download_gb:model==='small'?0.5:1.6}))),
    workers:{asr:{ready:true,models:{small:{ready:true},'large-v3-turbo':{ready:true}}},diar:{ready:true}},active_session:null,busy:false,
    jobs:[{id:'initial',action:'install',status:'completed',stage:'completed',message:'모델 설치가 완료되었습니다.',progress:100,created_at:'2026-09-14T00:00:00+00:00',finished_at:'2026-09-14T00:03:00+00:00',error:null}],
    updates:{supported:false,reason:'배포 채널 준비 중'},storage:{free_bytes:150*1024**3},
    access:{local_url:'http://127.0.0.1:8765',remote_url:'https://meetingbot-test.synthetic-tailnet.ts.net',kind:'tailscale'}
  };
  let config={version:0,chunk_tokens:256,overlap_tokens:32,top_k:6,updated_at:null,limits:{chunk_tokens:{min:32,max:400},overlap_tokens:{min:0,max:399},top_k:{min:1,max:12}},reindex_required:false,workspaces:[{workspace_id:'demo',name:'제품 회의 자료',active_revision_id:'r1',chunk_count:128,requires_reindex:false,has_source:true,indexing:false}]};
  let indexJob=null, embedding={state:'READY',model:'multilingual-e5-small'};
  const prompt={id:'p1',sequence:1,name:'기본 답변 지침',content:'제공된 자료의 근거를 바탕으로 질문에 정확히 답변하세요.',note:'',created_at:1780000000,restored_from_id:null};
  const llm={version:1,base_url:'http://127.0.0.1:8317/v1',default_model:'sample-model',enabled:false,api_key_present:false,max_output_tokens:2048,timeout_seconds:60,temperature:null,reasoning_effort:null,input_chars:12000,last_check:null};
  await page.route('**/api/**',async route=>{
    const request=route.request(), p=new URL(request.url()).pathname, method=request.method();
    report.requests.push({path:p,method});
    let data;
    if(p==='/api/system') data=status;
    else if(p==='/api/system/install'||p==='/api/system/selection') {
      const b=request.postDataJSON();
      const job={id:'job'+status.jobs.length,action:p.endsWith('install')?'install':'selection',status:'completed',stage:'completed',message:p.endsWith('install')?'설치가 완료되었습니다. 사용하기를 눌러 적용하세요.':'새 음성 설정을 적용했습니다.',progress:100,created_at:new Date().toISOString(),finished_at:new Date().toISOString(),error:null};
      if(p.endsWith('install')) {status.models.find(m=>m.engine===b.engine&&m.model===b.model).installed=true;status.engines.find(e=>e.id===b.engine).installed=true;}
      else status.selection=b;
      status.jobs.unshift(job);data=job;
    }
    else if(p==='/api/rag/auth/session') data={csrf:'synthetic-csrf'};
    else if(p==='/api/rag/settings') {
      if(method==='PUT') {assert.equal(request.headers()['x-csrf-token'],'synthetic-csrf');const b=request.postDataJSON();assert.equal(b.expected_version,config.version);config={...config,...b,version:config.version+1,reindex_required:true,workspaces:config.workspaces.map(w=>({...w,requires_reindex:true}))};delete config.expected_version;}
      data=config;
    }
    else if(p==='/api/rag/embedding') data=embedding;
    else if(p==='/api/rag/workspaces') data=[{id:'demo',name:'제품 회의 자료',document_count:12,latest_job:indexJob}];
    else if(p==='/api/rag/workspaces/demo/index-jobs') {config.workspaces[0].indexing=true;indexJob={job_id:'j1',state:'RUNNING',workspace_id:'demo',result:{}};data=indexJob;}
    else if(p==='/api/rag/llm/settings') data=llm;
    else if(p==='/api/rag/llm/models') data={models:['sample-model']};
    else if(p==='/api/rag/llm/codex/status') data={installed:false,connected:false};
    else if(p==='/api/rag/prompts') data={active_id:'p1',versions:[prompt]};
    else if(p==='/api/rag/prompts/active') data=prompt;
    else if(p==='/api/stt/health') data={engine:'fake',workers:status.workers,active_session:null,limits:{file_mb:4096,file_seconds:18000,live_seconds:300},environment:status.platform};
    else if(p==='/api/stt/sessions') data=[];
    else {report.errors.push(`Unexpected ${method} ${p}`);return route.fulfill({status:404,json:{message:'Unexpected fixture API'}});}
    await route.fulfill({json:data,status:method==='POST'?202:200});
  });
  const nav = label=>page.getByRole('navigation',{name:'관리 메뉴'}).getByRole('button',{name:label});
  await page.goto(base+'/settings');
  await page.getByText('150.0 GB 여유').waitFor();
  await page.screenshot({path:path.join(output,'settings-desktop.png'),fullPage:true});
  await page.getByRole('group',{name:'글자 크기'}).getByRole('button',{name:'크게',exact:true}).click();
  assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).fontSize),'18px');
  await page.reload();
  assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).fontSize),'18px');
  await page.getByRole('group',{name:'글자 크기'}).getByRole('button',{name:'기본',exact:true}).click();
  report.checks.push('Direct settings route, live server status, browser-persisted type preference');
  await nav('음성 인식').click();
  assert.equal(await page.getByText('Invalid Date').count(),0);
  const fasterEngine=page.locator('.management-card').filter({has:page.getByRole('heading',{name:'Faster Whisper',exact:true})});
  await fasterEngine.getByRole('button',{name:'설치하기',exact:true}).first().click();
  await page.getByRole('button',{name:'서버 상태 새로고침'}).click();
  await fasterEngine.getByRole('button',{name:'이 모델 사용',exact:true}).first().click();
  await page.getByRole('button',{name:'서버 상태 새로고침'}).click();
  await page.waitForFunction(()=>document.querySelector('.management-info')?.textContent.includes('Faster Whisper'));
  assert.equal(status.selection.engine,'faster-whisper');
  await page.screenshot({path:path.join(output,'speech-desktop.png'),fullPage:true});
  report.checks.push('ISO install dates render, allowlisted model install request, completion and activation affordance');
  await nav('자료 검색').click();
  await page.locator('#chunk-size').fill('128');
  await nav('AI 모델').click();
  await page.getByLabel('기본 모델',{exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'ai-desktop.png'),fullPage:true});
  await nav('자료 검색').click();
  assert.equal(await page.locator('#chunk-size').inputValue(),'128');
  await page.locator('#chunk-overlap').fill('128');
  assert.equal(await page.getByRole('button',{name:'설정 저장',exact:true}).isDisabled(),true);
  await page.locator('#chunk-overlap').fill('24');
  await page.getByRole('button',{name:'설정 저장',exact:true}).click();
  await page.getByRole('button',{name:'재색인',exact:true}).click();
  await page.getByRole('button',{name:'재색인 중',exact:true}).waitFor();
  indexJob.state='FAILED';config.workspaces[0].indexing=false;
  await page.getByText('최근 색인: 실패',{exact:false}).waitFor();
  config={...config,version:config.version+1,chunk_tokens:384,overlap_tokens:48};
  await page.waitForFunction(()=>document.querySelector('#chunk-size')?.value==='384');
  embedding={...embedding,state:'NOT_READY',error_code:'MODEL_NOT_READY'};
  await page.getByText('검색 모델 준비에 실패했습니다.',{exact:false}).waitFor();
  embedding={state:'READY',model:'multilingual-e5-small'};
  report.checks.push('RAG direct session/CSRF, unsaved form preserved across tabs, overlap validation, persisted settings and reindex, failed index/embedding visible, pristine external version refresh');
  await page.screenshot({path:path.join(output,'rag-desktop.png'),fullPage:true});
  await nav('설치 및 업데이트').click();
  await page.getByRole('button',{name:'접속 주소 복사',exact:true}).click();
  await page.getByText('접속 주소를 복사했습니다.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__clipboardWrites.at(-1)),status.access.remote_url);
  await page.getByRole('button',{name:'내 기기 접속 링크 복사',exact:true}).click();
  await page.getByText('내 기기 접속 링크를 복사했습니다.',{exact:true}).waitFor();
  assert.equal(await page.evaluate(()=>window.__clipboardWrites.at(-1)),status.access.remote_url+'/#token=synthetic');
  assert.equal(await page.locator('body').innerText().then(text=>text.includes('#token=synthetic')),false);
  await page.evaluate(()=>{window.__clipboardReject=true;});
  await page.getByRole('button',{name:'접속 주소 복사',exact:true}).click();
  await page.getByText('주소를 복사하지 못했습니다.',{exact:false}).waitFor();
  assert.equal(await page.getByText('내 기기 접속 링크를 복사했습니다.',{exact:true}).count(),0);
  await page.evaluate(()=>{window.__clipboardReject=false;});
  await page.getByRole('button',{name:'접속 주소 복사',exact:true}).click();
  await page.getByText('접속 주소를 복사했습니다.',{exact:true}).waitFor();
  assert.equal(await page.getByText('주소를 복사하지 못했습니다.',{exact:false}).count(),0);
  const remoteAddress=status.access.remote_url;
  status.access.remote_url=null;status.access.kind=null;
  await page.getByRole('button',{name:'서버 상태 새로고침'}).click();
  await page.getByText('접속 주소 미설정',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'접속 주소 복사',exact:true}).count(),0);
  status.access.remote_url=remoteAddress;status.access.kind='tailscale';
  await page.getByRole('button',{name:'서버 상태 새로고침'}).click();
  await page.getByText('접속 주소 설정됨',{exact:true}).waitFor();
  await page.screenshot({path:path.join(output,'updates-desktop.png'),fullPage:true});
  report.checks.push('Configured remote address and private connection link copied only on click; clipboard failure and retry; no token displayed; missing remote URL fallback');
  for(const width of [1440,1024,768,390]) {
    await page.setViewportSize({width,height:1000});
    for(const label of ['관리 홈','음성 인식','자료 검색','AI 모델','설치 및 업데이트']) {
      await nav(label).click();
      await page.waitForTimeout(80);
      const layout=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,header:document.querySelector('.workspace-header').getBoundingClientRect().toJSON(),brand:document.querySelector('.workspace-brand').getBoundingClientRect().toJSON()}));
      assert.ok(layout.scroll<=layout.width+1,`${width}px ${label} overflows ${layout.scroll}`);
      assert.ok(layout.brand.top>=0,`${width}px brand clipped`);
    }
  }
  await nav('관리 홈').click();
  await page.waitForTimeout(180);
  await page.screenshot({path:path.join(output,'settings-mobile.png'),fullPage:true});
  report.checks.push('All five management sections at 1440/1024/768/390px without horizontal overflow or clipped brand');
  assert.equal(report.errors.length,0,JSON.stringify(report.errors));
} finally { if(browser) await browser.close();server.kill('SIGTERM');await writeFile(path.join(output,'results.json'),JSON.stringify(report,null,2)); }
console.log(JSON.stringify({checks:report.checks,errors:report.errors,output},null,2));
