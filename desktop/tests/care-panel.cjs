// Production component, synthetic IPC. This does not measure model quality or native activation.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { resolve, basename } = require('node:path');
(async () => {
  const { createServer } = await import('vite');
  const root = resolve(__dirname,'..'),fixture = mkdtempSync(resolve(__dirname,'.care-'));
  writeFileSync(resolve(fixture,'index.html'), `<div id="root"></div><script type="module">
    import React from 'react'; import { createRoot } from 'react-dom/client'; import { CarePanel } from '/src/components/CarePanel.tsx';
    window.view = {policy:{revision:0,enabled:true,timezone:'Asia/Shanghai',start_hour:9,end_hour:23},items:[{id:'one',revision:1,title:'面试',fact:'我明天有面试，<img src="https://example.invalid/x">',status:'active',next_at:1793760000}]};
    window.calls=[]; window.presetCount=0;
    window.lobuddy={request:async(method,params)=>{window.calls.push({method,params});
      if(method==='care.update'){if(params.revision!==window.view.items[0].revision)throw Error('stale revision');window.view.items[0].revision++;window.view.items[0].status={pause:'paused',resume:'active',close:'closed',defer:'deferred'}[params.action];}
      if(method==='care.configure')window.view.policy={...params,revision:params.revision+1};
      if(method==='care.preset'){window.presetCount++;return window.view.policy;}
      return structuredClone(window.view);}};
    createRoot(document.getElementById('root')).render(React.createElement(CarePanel,{onPresetApplied:()=>window.applied=true}));
  </script>`);
  const server = await createServer({root,configFile:false,server:{host:'127.0.0.1',port:0}}); let browser;
  try {
    await server.listen(); browser=await chromium.launch({executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE||undefined});
    const page=await browser.newPage();page.setDefaultTimeout(10000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(server.resolvedUrls.local[0]+'tests/'+basename(fixture)+'/index.html');
    await page.getByRole('heading',{name:'面试 · 惦记着'}).waitFor();
    await page.getByText('来源原话',{exact:true}).click();assert.equal(await page.locator('article img').count(),0);
    await page.getByRole('button',{name:'暂时别再问',exact:true}).click();await page.getByRole('heading',{name:'面试 · 暂时不再问'}).waitFor();
    await page.getByRole('button',{name:'恢复关心',exact:true}).click();await page.getByRole('heading',{name:'面试 · 惦记着'}).waitFor();
    assert.deepEqual(await page.evaluate(()=>window.calls.filter(x=>x.method==='care.update').map(x=>x.params.revision)),[1,2]);
    await page.getByLabel('允许持续关心普通近况',{exact:true}).uncheck();await page.waitForFunction(()=>!window.view.policy.enabled);
    await page.getByRole('button',{name:'应用有存在感预设',exact:true}).click();await page.waitForFunction(()=>window.applied===true);
    assert.equal(await page.evaluate(()=>window.presetCount),1);assert.deepEqual(errors,[]);console.log('Care panel source, revisions, controls and preset reconciliation passed');
  } finally {if(browser)await browser.close();await server.close();rmSync(fixture,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
