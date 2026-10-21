import { access,lstat } from 'node:fs/promises';
import { constants } from 'node:fs';
import { dirname,join,resolve } from 'node:path';
import { createRequire } from 'node:module';
import { DatabaseSync } from 'node:sqlite';
import { hashFile } from './storage/files.js';
import { inspectDatabase,STORAGE_VERSION } from './storage/database.js';
export type HealthItem = {name:string;state:'ok'|'unavailable'|'optional';detail:string};
export type HealthOptions = {root:string;data:string;workspace:string;binary:string;binarySha256:string;model:string;baseUrl:string;credentialConfigured:boolean};
async function accessible(path:string){
  let current=resolve(path);
  for(;;){try{if(!(await lstat(current)).isDirectory())return false;await access(current,constants.W_OK|constants.X_OK);return true;}
    catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')return false;const parent=dirname(current);if(parent===current)return false;current=parent;}}
}
export async function inspectDesktop(options:HealthOptions){
  const checks:HealthItem[]=[];
  const add=(name:string,ok:boolean,detail:string)=>checks.push({name,state:ok?'ok':'unavailable',detail});
  add('data_directory',await accessible(options.data),'只检查已有目录或最近父目录权限，不创建资料');
  add('workspace',await accessible(options.workspace),'只检查已有目录或最近父目录权限，不执行任务');
  let model=options.model,baseUrl=options.baseUrl;
  try{
    const path=join(options.data,'lobuddy.db');let exists=true;
    try{await lstat(path);}catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')exists=false;else throw error;}
    if(exists){
      const db=new DatabaseSync(path,{readOnly:true,allowExtension:false,timeout:2000});
      try{
        const state=inspectDatabase(db);add('database',state.version===STORAGE_VERSION,'只读检查完整性与存储版本；旧库须先备份导入');
        for(const row of db.prepare('SELECT key,value FROM app_settings').all()){
          if(row.key==='llm_model')model=String(row.value);if(row.key==='llm_base_url')baseUrl=String(row.value);
        }
      }finally{db.close();}
    }else add('database',true,'尚未初始化，本次不创建数据库');
  }catch{add('database',false,'数据库无法读取或版本不支持；未重建或迁移');}
  let address=false;try{const url=new URL(baseUrl);address=['http:','https:'].includes(url.protocol)&&!url.username&&!url.password&&!url.hash;}catch{/* Invalid configuration is not printed. */}
  add('model_configuration',options.credentialConfigured&&Boolean(model.trim())&&address,'仅检查配置齐全；不验证凭据解密、远端模型或额度');
  try{
    const require=createRequire(import.meta.url),sdk=require('@deepseek-ai/dsh-sdk-client/package.json');
    await access(options.binary,constants.X_OK);
    add('dsh_runtime',sdk.version==='0.1.5-rc.1'&&await hashFile(options.binary)===options.binarySha256,'已锁定 SDK 版本与可执行文件 SHA256');
  }catch{add('dsh_runtime',false,'DSH 运行文件、版本或权限不可用');}
  try{add('plugin_bridge',(await lstat(join(options.root,'bridge/dsh/dist/index.js'))).isFile(),'已构建插件入口；本检查不启动引擎');}catch{add('plugin_bridge',false,'插件入口缺失');}
  checks.push({name:'voice',state:'optional',detail:'模型、设备、Fish 额度及回声须单独验收；不阻塞文字'});
  return {ready:checks.every(item=>item.state!=='unavailable'),scope:'本地只读检查；不联网、不采音、不解密凭据、不恢复任务',checks};
}
