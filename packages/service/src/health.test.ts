import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,mkdir,writeFile,readFile,rm,access} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {createHash} from 'node:crypto';
import {inspectDesktop,type HealthOptions} from './health.js';
import {Store} from './storage/database.js';
async function fixture(){
 const root=await mkdtemp(join(tmpdir(),'lobuddy-health-'));await mkdir(join(root,'bridge/dsh/dist'),{recursive:true});await writeFile(join(root,'bridge/dsh/dist/index.js'),'// synthetic');
 const binary=join(root,'dsh');await writeFile(binary,'synthetic-binary',{mode:0o700});
 const options:HealthOptions={root,data:join(root,'data'),workspace:join(root,'workspace'),binary,binarySha256:createHash('sha256').update('synthetic-binary').digest('hex'),model:'test',baseUrl:'https://example.com',credentialConfigured:true};
 return {root,options,close:()=>rm(root,{recursive:true,force:true})};
}
test('read-only health creates no data, work directory, engine or credential process',async()=>{
 const f=await fixture();try{const report=await inspectDesktop(f.options);assert.equal(report.ready,true);await assert.rejects(access(f.options.data));await assert.rejects(access(f.options.workspace));assert.equal(report.checks.find(x=>x.name==='voice')!.state,'optional');}finally{await f.close();}
});
test('health respects stored empty model and never rewrites a healthy database',async()=>{
 const f=await fixture();try{const path=join(f.options.data,'lobuddy.db'),store=new Store(path,{create:true});store.run("INSERT INTO app_settings VALUES('llm_model','','now')");store.close();const bytes=await readFile(path);const report=await inspectDesktop(f.options);assert.equal(report.ready,false);assert.equal(report.checks.find(x=>x.name==='model_configuration')!.state,'unavailable');assert.deepEqual(await readFile(path),bytes);}finally{await f.close();}
});
test('health leaves corrupt data intact and rejects missing plugin and mismatched runtime',async()=>{
 const f=await fixture();try{await mkdir(f.options.data);const path=join(f.options.data,'lobuddy.db');await writeFile(path,'broken');await rm(join(f.root,'bridge'),{recursive:true});f.options.binarySha256='0'.repeat(64);const report=await inspectDesktop(f.options);assert.deepEqual(report.checks.filter(x=>x.state==='unavailable').map(x=>x.name),['database','dsh_runtime','plugin_bridge']);assert.equal(await readFile(path,'utf8'),'broken');}finally{await f.close();}
});
test('health reports fixed diagnostics instead of private model or invalid URL values',async()=>{
 const f=await fixture();try{f.options.baseUrl='secret-value-invalid';f.options.model='private-model-name';f.options.credentialConfigured=false;const report=await inspectDesktop(f.options);assert.equal(report.ready,false);assert.doesNotMatch(JSON.stringify(report),/secret-value|private-model-name/);}finally{await f.close();}
});

test('health CLI rejects invalid arguments without printing supplied secrets',async()=>{
 const {spawnSync}=await import('node:child_process');const {fileURLToPath}=await import('node:url');
 const result=spawnSync(process.execPath,[fileURLToPath(new URL('../../../scripts/ts/health.mjs',import.meta.url)),'--invalid','private-synthetic-value'],{encoding:'utf8'});
 assert.equal(result.status,1);assert.doesNotMatch(result.stdout+result.stderr,/private-synthetic-value/);assert.match(result.stderr,/本地健康检查未完成/);
});
