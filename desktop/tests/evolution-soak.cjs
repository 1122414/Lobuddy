// Wall-clock desktop + TypeScript soak; synthetic data, microphone stays off.
const {_electron:electron}=require('playwright');
const {mkdtempSync,writeFileSync,rmSync,mkdirSync}=require('node:fs');
const {execFileSync}=require('node:child_process');
const {tmpdir}=require('node:os');
const {join,resolve}=require('node:path');
const assert=require('node:assert/strict');
const duration=Number(process.env.LOBUDDY_SOAK_SECONDS||7200);
const root=resolve(__dirname,'../..');
const report=resolve(root,process.env.LOBUDDY_SOAK_REPORT||'reports/2026-10-16_e5_soak.json');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function processes(rootPid){
  const rows=execFileSync('ps',['-axo','pid=,ppid=,rss='],{encoding:'utf8'}).trim().split('\n').map(l=>l.trim().split(/\s+/).map(Number));
  const ids=new Set([rootPid]);let changed=true;
  while(changed){changed=false;for(const [pid,parent] of rows)if(ids.has(parent)&&!ids.has(pid)){ids.add(pid);changed=true;}}
  return rows.filter(([pid])=>ids.has(pid));
}
(async()=>{
 const temporary=mkdtempSync(join(tmpdir(),'lobuddy-e5-soak-'));let app;const samples=[];let childIds=[];let tasks=0;
 const started=Date.now();const status={status:'running',started_at:new Date(started).toISOString(),duration_seconds:duration,scope:'isolated hidden Electron windows + TypeScript; no microphone/model requests',samples};
 try{
  mkdirSync(join(temporary,'workspace'));writeFileSync(join(temporary,'workspace/note.txt'),'决定：保留来源。\n待办：验证重复运行。');
  const bootstrap=join(temporary,'start.cjs');
  writeFileSync(bootstrap,`const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temporary,'electron'))});app.setAppPath(${JSON.stringify(join(root,'desktop'))});require(${JSON.stringify(join(root,'desktop/dist-electron/desktop/electron/main.js'))});`);
  app=await electron.launch({args:[bootstrap],env:{...process.env,LOBUDDY_DATA_DIR:join(temporary,'data'),LOBUDDY_WORKSPACE:join(temporary,'workspace')}});
  const page=await app.firstWindow();await page.getByText('服务已连接',{exact:true}).waitFor();
  await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().forEach(w=>w.hide()));
  const call=(method,params)=>page.evaluate(([method,params])=>window.lobuddy.request(method,params,crypto.randomUUID()),[method,params]);
  // Isolate persistence/resource checks from paid model traffic.
  await call('learning.configure',{enabled:false});
  const pid=app.process().pid;
  while(Date.now()-started<duration*1000){
   const session=await call('session.create',{title:'合成持续验收'});
   const turn=await call('turn.send',{session_id:session.id,text:'归纳测试资料',lane:'background',workflow_id:'source-digest',workflow_input:{sources:['note.txt']}});
   let final;
   for(let i=0;i<100;i++){final=await call('task.get',{turn_id:turn.turn_id});if(!['queued','running'].includes(final.status))break;await pause(50);}
   assert.equal(final.status,'completed');assert.equal((await call('task.outcome',{turn_id:turn.turn_id})).verdict,'verified');
   assert.equal((await call('learning.get',{})).state,'disabled');if((await call('service.health',{})).voice_available)assert.equal((await call('voice.get',{})).state,'off');tasks++;
   const tree=processes(pid);childIds=tree.map(row=>row[0]);
   samples.push({seconds:Math.round((Date.now()-started)/1000),rss_kib:tree.reduce((sum,row)=>sum+row[2],0),processes:tree.length});
   writeFileSync(report,JSON.stringify({...status,tasks},null,2));
   if(tasks%20===0)console.log(`SOAK ${samples.at(-1).seconds}s: ${tasks} verified synthetic runs, ${tree.length} processes`);
   await pause(Math.min(30000,Math.max(1,duration*1000-(Date.now()-started))));
  }
  const average=rows=>rows.reduce((sum,row)=>sum+row.rss_kib,0)/rows.length;
  const n=Math.min(20,Math.floor(samples.length/3));assert.ok(n>=1);
  const baseline=average(samples.slice(n,2*n)),end=average(samples.slice(-n));
  assert.ok(end-baseline<65536,`RSS drift ${(end-baseline)/1024} MiB exceeds fixed 64 MiB limit`);
  await app.close();app=null;await pause(1000);
  const alive=new Set(execFileSync('ps',['-axo','pid='],{encoding:'utf8'}).trim().split(/\s+/).map(Number));
  const orphans=childIds.filter(pid=>alive.has(pid));assert.deepEqual(orphans,[]);
  writeFileSync(report,JSON.stringify({...status,status:'passed',ended_at:new Date().toISOString(),elapsed_seconds:Math.round((Date.now()-started)/1000),tasks,rss_growth_kib:end-baseline,orphans},null,2));
  console.log(`PASS: ${duration}s wall-clock desktop/service soak, ${tasks} verified runs; no orphan process`);
 }catch(error){writeFileSync(report,JSON.stringify({...status,status:'failed',tasks,error:String(error)},null,2));throw error;}
 finally{if(app)await app.close();rmSync(temporary,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
