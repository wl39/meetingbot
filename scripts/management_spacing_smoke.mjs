/** Synthetic settings layout coverage only; all API calls are mocked and no settings are saved. */
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const base=process.env.MANAGEMENT_SPACING_QA_URL||'http://127.0.0.1:5173';
const output=new URL('../.runtime/management-spacing-qa/',import.meta.url).pathname;
await mkdir(output,{recursive:true});
const report={synthetic:true,checks:[],errors:[],requests:[],layouts:[]};
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.on('pageerror',e=>report.errors.push(e.message));
page.setDefaultTimeout(10000);
await page.addInitScript(()=>{
  sessionStorage.setItem('stt-token','synthetic');
  localStorage.setItem('meetingbot:getting-started:v1:spacing-admin',JSON.stringify({step:'dismissed',source:'own',workspaceId:null}));
  // Isolate a running fixture from concurrent development HMR updates.
  window.WebSocket=class { static OPEN=1; readyState=1; constructor(){setTimeout(()=>this.onopen?.({}),0)} send(){} close(){} };
  Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{throw new Error('Synthetic clipboard failure')}}});
});
try {
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
    if(method!=='GET'&&!['/api/events','/api/rag/auth/session'].includes(p)) throw new Error('No setting mutation permitted in layout coverage: '+p);
    let data;
    if(p==='/api/access/session') data={authenticated:true,role:'superadmin',account:{id:'spacing-admin',label:'검증 관리자',role:'superadmin'},demo:false,keyless:false,csrf:'synthetic-csrf',limits:{seconds:300,file_mb:30,jobs_per_visitor:5,jobs_daily:50}};
    else if(p==='/api/system/theme') data={color:'#b85c12'};
    else if(p==='/api/access/keys') data={keys:[{id:'key-1',label:'연구개발제품운영팀 회의 자료를 검토하는 담당자 '+ 'long-account-name-'.repeat(8),role:'admin',created:1780000000,revoked:null},{id:'key-2',label:'지난 행사 진행팀',role:'visitor',created:1780000000,revoked:1780000010}]};
    else if(p==='/api/events') data={};
    else if(p==='/api/system') data=status;
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

  const nav=label=>page.getByRole('navigation',{name:'관리 메뉴'}).getByRole('button',{name:label});
  await page.goto(base+'/settings');
  await page.getByText('150.0 GB 여유').waitFor();
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:1000});
    for(const label of ['관리 홈','음성 인식','자료 검색','접속 및 권한','설치 및 업데이트','AI 모델']) {
      await nav(label).click();
      await page.locator('.management-page-title h1').filter({hasText:label==='관리 홈'?'설정 및 관리':label}).waitFor();
      if(label==='자료 검색') await page.locator('#chunk-size').waitFor();
      if(label==='AI 모델') await page.getByLabel('기본 모델',{exact:true}).waitFor();
      await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
      const layout=await page.evaluate(()=>{
        const cards=[...document.querySelectorAll('.management-card')].filter(el=>el.getBoundingClientRect().width>0);
        return {width:innerWidth,scroll:document.documentElement.scrollWidth,
          padding:[...new Set(cards.map(el=>getComputedStyle(el).paddingLeft))],
          expectedPadding:getComputedStyle(document.documentElement).getPropertyValue('--card-padding').trim(),
          overflowing:cards.filter(el=>el.scrollWidth>el.clientWidth+1).map(el=>el.querySelector('h2')?.textContent),
          smallControls:[...document.querySelectorAll('.management-primary,.management-secondary,.management-segmented button,.access-settings button')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.height<43}).map(el=>el.textContent)
        };
      });
      report.layouts.push({label,...layout});
      assert(layout.scroll<=width+1,`${width} ${label} page overflow ${layout.scroll}`);
      assert.deepEqual(layout.overflowing,[],`${width} ${label} card overflow`);
      assert.deepEqual(layout.smallControls,[],`${width} ${label} controls under 44px`);
      assert(layout.padding.every(value=>value===(width<=720?'16px':'24px')),`${width} ${label} consistent card padding: ${layout.padding}`);
      if((width===1440&&label==='관리 홈')||(width===390&&['자료 검색','접속 및 권한'].includes(label)))
        await page.screenshot({path:output+width+'-'+label+'.png',fullPage:true});
    }
  }
  await page.setViewportSize({width:390,height:1000});
  await nav('관리 홈').click();
  await page.getByRole('group',{name:'글자 크기',exact:true}).getByRole('button',{name:'크게',exact:true}).click();
  await page.getByRole('group',{name:'화면 간격',exact:true}).getByRole('button',{name:'촘촘하게',exact:true}).click();
  for(const label of ['관리 홈','접속 및 권한','자료 검색','설치 및 업데이트']) {
    await nav(label).click();
    const metrics=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,paddings:[...document.querySelectorAll('.management-card')].filter(el=>el.getBoundingClientRect().width).map(el=>getComputedStyle(el).paddingLeft)}));
    assert(metrics.scroll<=metrics.width+1,`Large text/compact ${label} fits`);
    assert(metrics.paddings.every(value=>value==='16px'),`Large text/compact ${label} retains mobile padding`);
  }
  await nav('자료 검색').click();
  await page.locator('#chunk-overlap').fill('999');
  await page.locator('.management-field-error').waitFor();
  assert(await page.getByRole('button',{name:'설정 저장',exact:true}).isDisabled());
  await nav('설치 및 업데이트').click();
  await page.getByRole('button',{name:'접속 주소 복사',exact:true}).click();
  await page.getByText('주소를 복사하지 못했습니다.',{exact:false}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await page.screenshot({path:output+'390-large-compact-error.png',fullPage:true});
  report.checks.push('Six settings sections at 1440, 768, 390 and 320 px: no page/card overflow; consistent 24/16 px card padding; 44 px action controls');
  report.checks.push('Long access-key labels, large text with compact density, retrieval validation and dismissible clipboard errors remain readable');
  assert.deepEqual(report.errors,[]);
} catch(error) {
  report.failure=error.stack||String(error);
  await page.screenshot({path:output+'failure.png',fullPage:true}).catch(()=>{});
  process.exitCode=1;
} finally {
  await browser.close();
  await writeFile(output+'results.json',JSON.stringify(report,null,2));
}
console.log(JSON.stringify({checks:report.checks,errors:report.errors,failure:report.failure},null,2));
