const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const { Worker } = require('node:worker_threads');
const { ServiceClient } = require('../dist-electron/desktop/electron/service-client');

test('real TypeScript service validates, deduplicates and survives UI client changes', async () => {
  const { RpcClient,portTransport }=await import('@lobuddy/service');
  const temporary=mkdtempSync(join(tmpdir(),'lobuddy-electron-service-'));
  const worker=new Worker(resolve(__dirname,'../../packages/service/dist/node-host.js'),{workerData:{kind:'connect',storage:{data:join(temporary,'data'),workspace:join(temporary,'workspace'),logs:join(temporary,'logs'),create:true}}});
  const service=new ServiceClient();service.client=new RpcClient(portTransport({...worker,start(){},close(){worker.postMessage({kind:'close',instance_id:service.client.instanceId});},postMessage:value=>worker.postMessage(value),on:worker.on.bind(worker),off:worker.off.bind(worker)},'node'));
  service.exit=new Promise(resolve=>worker.once('exit',resolve));service.client.on('connected',value=>{service.connected=value;});service.starting=service.client.start();
  try {
    await service.handshake();assert.equal(service.connected,true);
    const first=await service.request('session.create',{title:'test'},'once');const repeat=await service.request('session.create',{title:'test'},'once');assert.equal(first.id,repeat.id);
    await assert.rejects(service.request('session.create',{title:'different'},'once'),error=>error.code==='id_conflict');
    await assert.rejects(service.request('shell.execute',{},'forbidden'));
    await assert.rejects(service.request('session.create',{title:'x',unknown:true},'invalid'));
    assert.equal((await service.request('session.list',{},'read')).length,1);
    await service.request('session.create',{title:'next'},'next');assert.equal((await service.request('session.list',{},'read')).length,2);
    assert.ok(service.client.requests.size<5);
    const omitted=await service.request('session.create',{title:undefined},'optional');
    assert.equal((await service.request('session.create',{},'optional')).id,omitted.id);
    await assert.rejects(service.request('session.create',{title:NaN},'invalid-number'));
  }finally{await Promise.all([service.stop(),service.stop()]);rmSync(temporary,{recursive:true,force:true});}
  assert.equal(service.connected,false);
});
