// A relocated app must use its bundled runtime, never a developer checkout or user site.
const { _electron: electron } = require('playwright');
const { mkdtempSync, readFileSync, cpSync, rmSync, mkdirSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { tmpdir } = require('node:os');
const assert = require('node:assert/strict');
const { waitFor } = require('./wait-for.cjs');
(async () => {
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-installed-'));
  let app;
  try {
    const source = readFileSync(join(__dirname, '../release/latest.txt'), 'utf8').trim();
    const target = join(temp, 'Relocated Lobuddy.app');
    cpSync(source, target, { recursive: true, verbatimSymlinks: true });
    const workspace = join(temp, 'workspace'); mkdirSync(workspace);
    writeFileSync(join(workspace, 'note.txt'), '决定：保留完整来源。');
    // Explicit provider settings stay in this process environment; never copy .env into the bundle.
    const configured=process.env.LOBUDDY_PACKAGE_REAL ? (await import('@lobuddy/service')).parseEnvironment(readFileSync(join(__dirname,'../../.env'),'utf8'),process.env) : {};
    const {SETTINGS_DESCRIPTORS}=await import('@lobuddy/contracts');
    const provider=Object.fromEntries(Object.entries(configured).filter(([key])=>Object.hasOwn(SETTINGS_DESCRIPTORS,key.toLowerCase())));
    const env = { HOME:process.env.HOME,TMPDIR:process.env.TMPDIR,...provider,PATH:'/usr/bin:/bin', LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: workspace,
      ...(!process.env.LOBUDDY_PACKAGE_REAL ? {LLM_API_KEY: 'synthetic-unused', LLM_MULTIMODAL_API_KEY: 'synthetic-unused', FISH_API_KEY: 'synthetic-unused',TYPESAFE_API_KEY:'synthetic-unused'} : {}) };
    app = await electron.launch({ executablePath: join(target, 'Contents/MacOS/Lobuddy'), args: [`--user-data-dir=${join(temp,'profile')}`], cwd: temp, env, timeout: 30000 });
    app.process().stderr.on('data',bytes=>{const match=/Business task failed: [A-Za-z_:]+/.exec(String(bytes));if(match)console.log(match[0]);});
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    assert.equal(await app.evaluate(({app}) => app.isPackaged), true);
    assert.equal(await app.evaluate(()=>process.env.PATH),'/usr/bin:/bin');
    await page.evaluate(async () => {
      const request = (method,params) => window.lobuddy.request(method,params,crypto.randomUUID());
      await request('learning.configure', {enabled:false});
      const session = await request('session.create', {title:'独立安装验证'});
      await request('turn.send', {session_id:session.id,text:'归纳明确文件',lane:'background',workflow_id:'source-digest',workflow_input:{sources:['note.txt']}});
    });
    await waitFor(page, async () => (await window.lobuddy.request('task.list',{},crypto.randomUUID()))[0]?.status === 'completed', null);
    const tasks = await page.evaluate(() => window.lobuddy.request('task.list',{},crypto.randomUUID()));
    assert.equal(tasks.length,1);
    const outcome = await page.evaluate(id => window.lobuddy.request('task.outcome',{turn_id:id},crypto.randomUUID()), tasks[0].turn_id);
    assert.equal(outcome.verdict, 'verified');
    if (process.env.LOBUDDY_PACKAGE_REAL) {
      const turn = await page.evaluate(async () => {
        const session = await window.lobuddy.request('session.create',{title:'随包真实模型'},crypto.randomUUID());
        return window.lobuddy.request('turn.send',{session_id:session.id,text:'请只回复你好。'},crypto.randomUUID());
      });
      await waitFor(page, async id => {
        const task = await window.lobuddy.request('task.get',{turn_id:id},crypto.randomUUID());
        if (['failed','interrupted','cancelled'].includes(task.status)) throw Error('Bundled real model task did not complete');
        return task.status==='completed' && task.output_text.length>0;
      }, turn.turn_id, {timeout:90000});
      console.log('PASS: relocated bundled DSH runtime and real configured model');
    }
    console.log('PASS: relocated standalone app, TypeScript handshake, verified source task, no global Node or checkout environment');
  } finally { if(app) await app.close(); rmSync(temp,{recursive:true,force:true}); }
})().catch(error=>{console.error(error);process.exitCode=1;});
