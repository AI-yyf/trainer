import { chromium } from 'playwright';
import fs from 'node:fs/promises';
const base = process.env.TRAINER_SURFACE_URL || 'http://127.0.0.1:4187';
const browser = await chromium.launch({headless:true});
const report = {source:'profiling-preview-real-react-synthetic-stream', cases:[],limitations:['Synthetic 300 chunks, not provider latency. Profiling bundle differs from shipping normal bundle. One-machine timing deltas are not quality proof.']};
try {
 for(const setup of ['coach-only','all-six','dirty-settings-large-reader']) {
  const page = await browser.newPage({viewport:{width:460,height:900}});
  await page.addInitScript(()=>{ window.__TRAINER_PROFILE_SURFACES__=true; });
  await page.goto(base+'/vscode-preview.html?view=coach&scenario=ready&connection=connected&lang=en-US&run='+setup);
  await page.waitForSelector('#root[data-trainer-app-ready="true"]');
  await page.evaluate(()=>{
    const conversation=Array.from({length:300},(_,i)=>({id:'history-'+i,role:i%2?'assistant':'user',author:'Trainer',body:'Explain this coding practice. '+i,timestamp:'12:00'}));
    const original=window.__TRAINER_BOOTSTRAP__;
    window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({type:'bootstrap',payload:{...original,conversation,
      memory:{...original.memory,sandboxPreview:{path:'/tmp/probe.txt',relativePath:'probe.txt',previewKind:'text',content:'large-reader-line\n'.repeat(10000)}}}});
  });
  const visit=async target=>{await page.evaluate(view=>window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({type:'ui/restoreView',payload:{activeView:view}}),target);await page.waitForSelector('div[data-surface="'+target+'"]:not([hidden])');};
  if(setup!=='coach-only')for(const view of ['plan','resources','training','progress','settings'])await visit(view);
  if(setup==='dirty-settings-large-reader'){
    const category=page.locator('[data-settings-category="connection"]');if(await category.count())await category.click();
    await page.getByRole('button',{name:'Edit configuration',exact:true}).click();
    const field=page.locator('[data-surface=settings] input:not([type=password]):not([type=checkbox])').first();
    await field.fill('https://dirty-form.invalid/v1');
    await visit('resources');
    await page.evaluate(()=>window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__({type:'ui/restoreView',payload:{activeView:'resources',resourceSurface:'sandbox',sandboxPath:'/tmp/probe.txt',previewPath:'/tmp/probe.txt'}}));
    await page.waitForSelector('[data-template=ResourceReader]');
  }
  await visit('coach'); await page.waitForTimeout(100);
  await page.evaluate(()=>{window.__TRAINER_SURFACE_METRICS__={};});
  const burst=await page.evaluate(async()=>{
    const apply=window.__TRAINER_PREVIEW_APPLY_HOST_MESSAGE__;const id='profile-'+Date.now();const longtasks=[];
    const obs=new PerformanceObserver(list=>longtasks.push(...list.getEntries().map(e=>e.duration)));obs.observe({entryTypes:['longtask']});
    const start=performance.now();apply({type:'stream/start',payload:{messageId:id}});
    for(let i=0;i<300;i++){apply({type:'stream/chunk',payload:{messageId:id,chunk:'Coach stream '+i+' '+('x'.repeat(70))}});await new Promise(r=>setTimeout(r,4));}
    await new Promise(r=>setTimeout(r,100));
    const visible=Boolean(document.querySelector('.message-bubble--streaming'));const metrics=structuredClone(window.__TRAINER_SURFACE_METRICS__);
    apply({type:'stream/complete',payload:{messageId:id,tokens:3000}});obs.disconnect();return {metrics,streamingRendered:visible,longtasks,durationMs:performance.now()-start};
  });
  report.cases.push({setup,...burst});
  if(!burst.streamingRendered||!Object.values(burst.metrics).some(m=>m.commits>0))throw new Error('No actual visible stream/profiling commits');
  await page.close();
 }
 await fs.writeFile(process.argv[2] || 'output/maturity/surface-before.json',JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
}finally{await browser.close();}
