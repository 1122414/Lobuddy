// Kill only this test's business owner while a real DSH write awaits approval.
const { _electron:electron }=require('playwright');
const {mkdtempSync,rmSync,existsSync,readdirSync,readFileSync,writeFileSync}=require('node:fs');
const {join,resolve}=require('node:path');const {tmpdir}=require('node:os');
const assert=require('node:assert/strict');const {waitFor}=require('./wait-for.cjs');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const alive=pid=>{try{process.kill(pid,0);return true;}catch{return false;}};
(async()=>{
 const root=resolve(__dirname,'../..'),temp=mkdtempSync(join(tmpdir(),'lobuddy-ts-owner-crash-'));let app,enginePid;
 const env={...process.env,LOBUDDY_DATA_DIR:join(temp,'data'),LOBUDDY_WORKSPACE:join(temp,'workspace')};
 const args=[resolve(__dirname,'..'),`--user-data-dir=${join(temp,'profile')}`];
 try{
  app=await electron.launch({args,env});let page=await app.firstWindow();await page.getByText('服务已连接',{exact:true}).waitFor();
  const session=await page.evaluate(()=>window.lobuddy.request('session.create',{title:'业务所有权故障验收'},crypto.randomUUID()));
  const turn=await page.evaluate(id=>window.lobuddy.request('turn.send',{session_id:id,text:'请调用 lobuddy_write_file 写入 crash-denied.txt，内容 synthetic。只尝试一次，拒绝后停止。'},crypto.randomUUID()),session.id);
  await page.getByRole('dialog').waitFor({timeout:90000});
  const metrics=await app.evaluate(({app})=>app.getAppMetrics().map(({pid,name,serviceName})=>({pid,name,serviceName})));
  const business=metrics.find(item=>item.name==='Lobuddy business'||item.serviceName==='Lobuddy business');assert.ok(business?.pid,'Owned business PID must be identifiable');
  for(const name of readdirSync(join(temp,'data/dsh'))){const path=join(temp,'data/dsh',name,'owner.pid');if(existsSync(path))enginePid=Number(readFileSync(path,'utf8'));}
  assert.ok(enginePid&&alive(enginePid));process.kill(business.pid,'SIGKILL');
  await waitFor(page,async()=>{try{await window.lobuddy.request('service.health',{},crypto.randomUUID());return false;}catch{return true;}});
  const deadline=Date.now()+15000;while(alive(enginePid)&&Date.now()<deadline)await pause(50);
  assert.equal(alive(enginePid),false,'DSH must terminate when its business owner dies');
  assert.equal(existsSync(join(temp,'workspace/crash-denied.txt')),false);
  await app.close();app=await electron.launch({args,env});page=await app.firstWindow();await page.getByText('服务已连接',{exact:true}).waitFor();
  const state=await page.evaluate(id=>window.lobuddy.request('task.get',{turn_id:id},crypto.randomUUID()),turn.turn_id);
  assert.equal(state.status,'interrupted');assert.equal((await page.evaluate(()=>window.lobuddy.request('approval.list',{},crypto.randomUUID()))).length,0);
  await pause(1000);assert.equal(existsSync(join(temp,'workspace/crash-denied.txt')),false);
  console.log('PASS: business SIGKILL closes real DSH, denies pending effect, restart interrupts without replay');
  writeFileSync(join(root,'.local-upgrade/t9-business-crash.json'),JSON.stringify({checks:['real DSH exits with killed business owner','pending write absent','restart interrupts and expires approval','unknown effect not replayed'],passed:true},null,2));
 }finally{if(app)await app.close();if(enginePid&&alive(enginePid)){process.kill(enginePid,'SIGKILL');console.error('Test cleanup killed an orphan; acceptance failed.');process.exitCode=1;}rmSync(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
