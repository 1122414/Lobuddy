// Test-only model transport: all native evaluation requests share the same durable daily ledger.
const {createServer}=require('node:http');
const {readFileSync}=require('node:fs');const {resolve}=require('node:path');const {parseEnv}=require('node:util');
async function evaluationProvider(){
  const root=resolve(__dirname,'../..'),settings=parseEnv(readFileSync(resolve(root,'.env'),'utf8'));
  const target=new URL(process.env.LLM_BASE_URL||settings.LLM_BASE_URL);
  if(!['http:','https:'].includes(target.protocol)||target.username||target.password||target.search)throw Error('invalid evaluation endpoint');
  const {reserveEvaluation}=await import('../../qualification/ts-runtime/dist/evaluation-budget.js');
  const routes=new Set(['chat/completions','responses'].map(route=>target.pathname.replace(/\/$/u,'')+'/'+route));
  let calls=0,budgetBlocked=false;
  const server=createServer(async(req,res)=>{
    try{
      if(req.method!=='POST'||!routes.has(req.url||'')){res.writeHead(404);res.end();return;}
      const chunks=[];let length=0;for await(const chunk of req){length+=chunk.length;if(length>256000)throw Error('request too large');chunks.push(chunk);}
      const body=JSON.parse(Buffer.concat(chunks).toString());
      // Cap this synthetic evaluation; never enlarge a production request's single-call allowance.
      const maximum=body.max_completion_tokens??body.max_tokens??1024;
      if(!Number.isSafeInteger(maximum)||maximum<1)throw Error('invalid model limit');
      if(body.max_completion_tokens!==undefined)body.max_completion_tokens=Math.min(maximum,1024);else body.max_tokens=Math.min(maximum,1024);
      const data=JSON.stringify(body);
      try{reserveEvaluation(resolve(root,'.local-upgrade/care-model-evaluation.json'),Buffer.byteLength(data),Math.min(maximum,1024));}
      catch{budgetBlocked=true;throw Error('evaluation budget unavailable');}
      calls++;
      const response=await fetch(target.origin+req.url,{method:'POST',headers:{'content-type':'application/json',...(req.headers.authorization?{authorization:req.headers.authorization}:{})},body:data,redirect:'error',signal:AbortSignal.timeout(60000)});
      if(!response.ok)throw Error('upstream unavailable');
      res.writeHead(200,{'content-type':response.headers.get('content-type')||'text/event-stream'});
      for await(const chunk of response.body)res.write(chunk);res.end();
    }catch{if(!res.headersSent)res.writeHead(503,{'content-type':'application/json'});res.end(JSON.stringify({error:{message:'evaluation unavailable'}}));}
  });
  await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(0,'127.0.0.1',resolve);});
  return {url:`http://127.0.0.1:${server.address().port}${target.pathname.replace(/\/$/u,'')}`,calls:()=>calls,budgetBlocked:()=>budgetBlocked,
    close:()=>new Promise(resolve=>{server.closeAllConnections();server.close(resolve);})};
}
module.exports={evaluationProvider};
