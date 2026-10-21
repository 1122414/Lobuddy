// Read-only Node CLI. The Electron UI verifies actual safeStorage access at startup.
import {readFile} from 'node:fs/promises';
import {join,resolve,dirname} from 'node:path';
import {homedir} from 'node:os';
import {fileURLToPath} from 'node:url';
import {parseEnvironment} from '../../packages/service/dist/config/settings.js';
import {inspectDesktop} from '../../packages/service/dist/health.js';
import {CredentialEnvelopeSchema} from '@lobuddy/contracts';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..');
try{
 const args=process.argv.slice(2),values={};
 for(let i=0;i<args.length;i+=2){if(!['--data-dir','--workspace'].includes(args[i])||!args[i+1])throw Error('Invalid arguments');values[args[i]]=resolve(args[i+1]);}
 const data=values['--data-dir']??join(homedir(),'Library/Application Support/lobuddy-desktop/typescript/data');
 const workspace=values['--workspace']??join(dirname(data),'workspace');
 let dotenv='';try{dotenv=await readFile(join(root,'.env'),'utf8');}catch(error){if(error.code!=='ENOENT')throw error;}
 const env=parseEnvironment(dotenv,process.env);let credentialConfigured=Boolean(env.LLM_API_KEY);
 if(!credentialConfigured)try{credentialConfigured=Boolean(CredentialEnvelopeSchema.parse(JSON.parse(await readFile(join(dirname(data),'credentials.json'),'utf8'))).entries.llm_api_key);}catch(error){if(error.code!=='ENOENT')throw error;}
 const native=JSON.parse(await readFile(join(root,'qualification/ts-runtime/native-manifest.json'),'utf8'));
 const report=await inspectDesktop({root,data,workspace,binary:join(root,'.local-upgrade/ts-assets/dsh-runtime'),binarySha256:native.dsh.runtimeSha256,model:env.LLM_MODEL??'',baseUrl:env.LLM_BASE_URL??'https://api.deepseek.com',credentialConfigured});
 console.log(JSON.stringify(report,null,2));process.exitCode=report.ready?0:1;
}catch{console.error('本地健康检查未完成；配置或资料不可用，未写入或重建。');process.exitCode=1;}
