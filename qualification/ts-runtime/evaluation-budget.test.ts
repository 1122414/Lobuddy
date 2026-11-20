import {test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,readFileSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {reserveEvaluation,evaluationAvailable} from './evaluation-budget.js';
test('evaluation reservation is durable across fixtures and failure cannot reset the daily allowance',()=>{
  const root=mkdtempSync(join(tmpdir(),'lobuddy-evaluation-ledger-')),path=join(root,'usage.json');
  try{
    reserveEvaluation(path,7000,1024);const first=JSON.parse(readFileSync(path,'utf8'));
    reserveEvaluation(path,7000,1024);const second=JSON.parse(readFileSync(path,'utf8'));assert.equal(second.calls,2);assert.equal(second.output,2048);
    writeFileSync(path,JSON.stringify({...second,output:19456}));
    assert.equal(evaluationAvailable(path,1,1024),false);
    assert.throws(()=>reserveEvaluation(path,1,1024),/exhausted/);assert.equal(JSON.parse(readFileSync(path,'utf8')).output,19456);
    writeFileSync(path,JSON.stringify({...first,day:'9999-01-01'}));assert.throws(()=>reserveEvaluation(path,1,1024),/clock/);
    writeFileSync(path,'invalid');assert.throws(()=>reserveEvaluation(path,1,1024));assert.equal(readFileSync(path,'utf8'),'invalid');
  }finally{rmSync(root,{recursive:true,force:true});}
});
