import { app } from 'electron';
import { readFile,access,mkdir } from 'node:fs/promises';
import { join,resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { createHash } from 'node:crypto';
import { openCredentialVault,readLegacyCredential } from './credential-vault';
import type { ServiceStartup } from './service-client';
import type { SecretField } from '@lobuddy/service' with { 'resolution-mode': 'import' };
const exists = async (path:string) => {try{await access(path);return true;}catch(error){if((error as NodeJS.ErrnoException).code==='ENOENT')return false;throw error;}};
export async function desktopStartup() {
  const {migrateCredentials,parseEnvironment,SECRET_FIELDS,createBackup,importBackup,requireStopped} = await import('@lobuddy/service');
  const {SETTINGS_DESCRIPTORS} = await import('@lobuddy/contracts');
  const root=app.isPackaged?app.getAppPath():resolve(app.getAppPath(),'..');
  const user=app.getPath('userData'),target=process.env.LOBUDDY_DATA_DIR?resolve(process.env.LOBUDDY_DATA_DIR):join(user,'typescript');
  // Imported layout keeps the old data/workspace snapshot separate and preserves its rollback source.
  let data=process.env.LOBUDDY_DATA_DIR?target:join(target,'data'),workspace=process.env.LOBUDDY_WORKSPACE?resolve(process.env.LOBUDDY_WORKSPACE):join(target,'workspace');
  const legacy=join(user,'service');
  if(!await exists(target)&&await exists(join(legacy,'lobuddy.db'))&&!process.env.LOBUDDY_DATA_DIR){
    await requireStopped(legacy);await mkdir(join(user,'upgrade-backups'),{recursive:true,mode:0o700});
    const backup=join(user,'upgrade-backups','typescript-'+Date.now());await createBackup(legacy,join(legacy,'workspace'),backup);
    const imported=await importBackup(backup,target);data=imported.data_dir;workspace=imported.workspace;
  }
  await mkdir(target,{recursive:true,mode:0o700});
  const dotenv=!app.isPackaged&&await exists(join(root,'.env'))?await readFile(join(root,'.env'),'utf8'):'';
  const environment=parseEnvironment(dotenv,process.env);
  const config=Object.fromEntries(Object.entries(environment).filter(([key])=>Object.hasOwn(SETTINGS_DESCRIPTORS,key.toLowerCase())&&!SECRET_FIELDS.includes(key.toLowerCase() as SecretField)).map(([key,value])=>[key.toUpperCase(),value]));
  const stored:Record<string,string>={};
  if(await exists(join(data,'lobuddy.db'))){
    const db=new DatabaseSync(join(data,'lobuddy.db'),{readOnly:true});
    try{for(const row of db.prepare('SELECT key,value FROM app_settings').all())stored[String(row.key)]=String(row.value);}finally{db.close();}
  }
  const vault=await openCredentialVault(join(target,'credentials.json'));
  const database:Partial<Record<SecretField,string>>={};for(const field of SECRET_FIELDS)if(stored[field])database[field]=stored[field];
  await migrateCredentials({vault,dotenv,environment:process.env,database,legacyKeychain:readLegacyCredential});
  const credentials:Partial<Record<SecretField,string>>={};for(const field of SECRET_FIELDS){const value=await vault.get(field);if(value)credentials[field]=value;}
  const baseUrl=stored.llm_base_url??environment.LLM_BASE_URL??'https://api.deepseek.com',model=stored.llm_model??environment.LLM_MODEL??'';
  const assets=app.isPackaged?join(root,'assets'):join(root,'.local-upgrade/ts-assets');
  const binary=join(assets,'dsh-runtime');
  const binarySha256='6f98dfe1745f6c952c6157dfade5ac2c6a8aeb672291b2c0703b21adf11cf88c';
  if(credentials.llm_api_key&&model&&await exists(binary)){
    const actual=createHash('sha256').update(await readFile(binary)).digest('hex');if(actual!==binarySha256)throw Error('DSH 运行文件校验失败');
  }
  const options:ServiceStartup={kind:'connect',root,speechModels:join(data,'voice-models/onnx-small'),storage:{data,workspace,logs:join(data,'logs'),create:!await exists(join(data,'lobuddy.db'))},credentials,config};
  if(credentials.llm_api_key&&model&&await exists(binary))options.engine={binary,binarySha256,plugin:join(root,'bridge/dsh/dist/index.js'),applicationRoot:root,apiKey:credentials.llm_api_key,baseUrl,model};
  return {options,vault,data};
}
