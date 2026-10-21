import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import { join } from 'node:path';
import type { ParametersByMethod } from '../../shared/desktop-protocol';
import type { ResultsByMethod } from '../../shared/desktop-api';
import type { ServiceConnectSchema, ParametersByMethod as RpcParameters } from '@lobuddy/contracts' with { 'resolution-mode': 'import' };
import type { z } from 'zod';
import type { RpcClient } from '@lobuddy/service' with { 'resolution-mode': 'import' };
export type ServiceStartup = z.infer<typeof ServiceConnectSchema> & { root: string; speechModels: string };
/** Main-process owner; renderer requests cannot select the runtime, paths, or credentials. */
export class ServiceClient extends EventEmitter {
  private client?: RpcClient;
  private child?: Electron.UtilityProcess;
  private speech?: { close(): void };
  private exit?: Promise<void>;
  private starting?: Promise<void>;
  private stopping?: Promise<void>;
  connected = false;
  start(options: ServiceStartup): void {
    if (this.starting) throw Error('Service already started');
    this.starting = this.launch(options); void this.starting.catch(error => {
      const name = error instanceof Error && /^[A-Za-z]+$/.test(error.name) ? error.name : 'StartupError';
      const code = ['ERR_MODULE_NOT_FOUND','MODULE_NOT_FOUND','ERR_DLOPEN_FAILED'].includes(error?.code) ? error.code : 'STARTUP_FAILED';
      this.emit('diagnostic',`${name}:${code}`);this.status(false);
    });
  }
  private async launch(options: ServiceStartup) {
    const { utilityProcess,MessageChannelMain } = await import('electron');
    const { RpcClient,portTransport } = await import('@lobuddy/service');
    const { hostSpeech } = await import('@lobuddy/speech/electron');
    const { root,speechModels,...connect } = options;
    const child = this.child = utilityProcess.fork(join(root,'packages/service/dist/utility-entry.cjs'),[],{
      stdio:'pipe',serviceName:'Lobuddy business',env:{PATH:'/usr/bin:/bin',HOME:process.env.HOME,ORT_DISABLE_TELEMETRY:'1'},
    });
    child.stdout?.on('data',()=>{});child.stderr?.on('data',bytes=>{
      const diagnostic=/LOBUDDY_STARTUP:(channel|contracts|modules|storage|server):(ERR_MODULE_NOT_FOUND|MODULE_NOT_FOUND|ERR_DLOPEN_FAILED|STARTUP_FAILED)/.exec(String(bytes));
      if(diagnostic)this.emit('diagnostic',diagnostic[0]);
    });
    this.exit = new Promise(resolve => child.once('exit',()=>{ this.client?.close();this.speech?.close();this.status(false);resolve(); }));
    const business = new MessageChannelMain(),speech = new MessageChannelMain();
    this.speech = hostSpeech(speech.port1,speechModels);
    const client = this.client = new RpcClient(portTransport(business.port1,'electron'));
    client.on('connected',(connected:boolean)=>this.status(connected));client.on('event',event=>this.emit('event',event));
    client.on('resync',()=>this.emit('resync'));
    child.postMessage(connect,[business.port2,speech.port2]); await client.start();
  }
  private status(connected: boolean) { this.connected=connected;this.emit('status',connected); }
  async handshake(): Promise<void> { if(!this.starting)throw Error('Service not started');await this.starting; }
  async request<M extends keyof ParametersByMethod>(method:M,params:unknown,id:string):Promise<ResultsByMethod[M]> {
    if(!this.client || this.stopping)throw Error('业务服务不可用，请重新启动应用。');
    const { requestSchemas } = await import('@lobuddy/contracts');
    // Preserve the former JSON transport's omitted optional fields, without converting
    // invalid numbers or objects into otherwise valid requests during serialization.
    if (!Object.hasOwn(requestSchemas,method) || !requestSchemas[method].safeParse(params).success) {
      throw Error('请求参数无效');
    }
    const wireParams: RpcParameters[M] = JSON.parse(JSON.stringify(params));
    return await this.client.request(method,wireParams,id) as ResultsByMethod[M];
  }
  async denyApprovals() {
    if(!this.connected || this.stopping)return;
    try {for(const item of await this.request('approval.list',{},randomUUID())) await this.request('approval.resolve',{approval_id:item.approval_id,approved:false},randomUUID()).catch(()=>{});}catch{/* Disconnected owners cannot approve work. */}
  }
  stop():Promise<void> { return this.stopping ??= this.shutdown(); }
  private async shutdown() {
    await this.starting?.catch(()=>{});this.speech?.close();this.client?.close();
    let timer:ReturnType<typeof setTimeout>|undefined;
    try {if(this.exit)await Promise.race([this.exit,new Promise<void>(resolve=>{timer=setTimeout(()=>{this.child?.kill();resolve();},15000);})]);}
    finally{clearTimeout(timer);this.status(false);}
  }
}
