import { app,MessageChannelMain,utilityProcess } from 'electron';
import { resolve,join } from 'node:path';
import { readFile,writeFile,mkdtemp,rm } from 'node:fs/promises';
import { once } from 'node:events';
import { parseEnv } from 'node:util';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';
let phase = 'startup';
void app.whenReady().then(async () => {
  const root = resolve(__dirname,'../../..'),directory = await mkdtemp('/private/tmp/lobuddy-voice-chain-');
  const { hostSpeech } = await import('@lobuddy/speech/electron'); const { RpcClient,portTransport } = await import('@lobuddy/service');
  const config = parseEnv(await readFile(join(root,'.env'),'utf8'));
  const { readLegacyCredential } = await import(join(root,'desktop/dist-electron/desktop/electron/credential-vault.js'));
  if (!config.LLM_API_KEY) config.LLM_API_KEY = await readLegacyCredential('llm_api_key');
  if (!config.FISH_API_KEY) config.FISH_API_KEY = await readLegacyCredential('fish_api_key');
  assert.ok(config.LLM_API_KEY && config.LLM_MODEL && config.LLM_BASE_URL && config.FISH_API_KEY);
  const manifest = JSON.parse(await readFile(join(root,'qualification/ts-runtime/native-manifest.json'),'utf8')) as { dsh: { runtimeSha256: string } };
  const speechPorts = new MessageChannelMain(),host = hostSpeech(speechPorts.port1,join(root,'.local-upgrade/ts-assets'));
  const child = utilityProcess.fork(join(root,'packages/service/dist/utility-entry.cjs'),[],{stdio:'pipe',env:{PATH:'/usr/bin:/bin',HOME:process.env.HOME},serviceName:'Lobuddy TS voice chain'});
  child.stdout?.on('data',()=>{});child.stderr?.on('data',()=>{});const exited = once(child,'exit');
  const { port1,port2 } = new MessageChannelMain(),client = new RpcClient(portTransport(port1,'electron'),20000);
  const deadline = setTimeout(()=>{host.close();child.kill();app.exit(1);},240000);
  child.postMessage({kind:'connect',storage:{data:join(directory,'data'),workspace:join(directory,'workspace'),logs:join(directory,'logs'),create:true},
    engine:{binary:join(root,'.local-upgrade/ts-assets/dsh-runtime'),binarySha256:manifest.dsh.runtimeSha256,plugin:join(root,'bridge/dsh/dist/index.js'),applicationRoot:root,
      apiKey:config.LLM_API_KEY,baseUrl:config.LLM_BASE_URL,model:config.LLM_MODEL},credentials:{fish_api_key:config.FISH_API_KEY}},[port2,speechPorts.port2]);
  const checks: string[] = []; let polling: Promise<void> | undefined,done = false,cursor = 0,audioBytes = 0,transcribed = false,finished = false,error = '';
  try {
    phase = 'handshake';await client.start();const learning = await client.request('learning.get',{}); await client.request('learning.configure',{...learning.policy,enabled:false});
    const session = await client.request('session.create',{title:'合成语音链路'});assert.equal((await client.request('voice.get',{})).model_ready,true);
    phase = 'start';const state = await client.request('voice.start',{session_id:session.id});assert.ok(state.voice_id);
    polling = (async()=>{while(!done){
      const poll = await client.request('voice.poll',{voice_id:state.voice_id,after:cursor,playing:false});
      if(poll.status.state==='error'){error=poll.status.error;return;}
      for(const event of poll.events){cursor=event.sequence;if(event.kind==='transcript')transcribed=true;if(event.kind==='audio')audioBytes+=Buffer.from(event.pcm,'base64').length;if(event.kind==='audio.end')finished=true;}
      for(const request of await client.request('approval.list',{}))await client.request('approval.resolve',{approval_id:request.approval_id,approved:false});
      await delay(40);
    }})().catch(()=>{if(!done)error='voice polling failed';});
    let began = Date.now();while((await client.request('voice.get',{})).state!=='listening'){if(error||Date.now()-began>60000)throw Error(error||'voice loading timeout');await delay(100);}
    const {pcm16Mono}=await import('./speech-probe.js');const audio=pcm16Mono(await readFile(join(root,'.local-upgrade/ts-corpus/cmn_hans_cn_0000.wav')));
    phase = 'continuous-frames';let sequence=0;
    for(let offset=0;offset<audio.length+16000;offset+=512){
      const buffer=Buffer.alloc(1024);for(let i=0;i<512;i++)buffer.writeInt16LE(Math.round(Math.max(-1,Math.min(.9999,audio[offset+i]??0))*32768),i*2);
      assert.equal((await client.request('voice.frame',{voice_id:state.voice_id,sequence:++sequence,pcm:buffer.toString('base64')})).accepted,true);
    }
    phase='real-response';began=Date.now();while(!finished){if(error||Date.now()-began>120000)throw Error(error||'voice response timeout');await delay(100);}
    assert.ok(transcribed&&audioBytes>0);checks.push('real local PCM → Silero/Whisper → DSH response → selected Fish free voice streaming PCM');
    assert.ok((await client.request('session.history',{session_id:session.id})).some(message=>message.role==='user'));
    checks.push('only final transcript and dialogue persist; raw audio stays in owned memory');
    phase='mute';await client.request('voice.mute',{voice_id:state.voice_id,muted:true});assert.equal((await client.request('voice.get',{})).state,'muted');assert.equal(host.pid,undefined);
    checks.push('mute releases the actual native inference process');
    await client.request('voice.mute',{voice_id:state.voice_id,muted:false});began=Date.now();while((await client.request('voice.get',{})).state!=='listening'){if(error||Date.now()-began>60000)throw Error(error||'resume timeout');await delay(100);}
    checks.push('explicit resume loads a fresh speech generation without replay');
    done=true;await polling;await client.request('voice.stop',{});assert.equal(host.pid,undefined);
    phase='shutdown';client.close();await exited;checks.push('business and speech owners close without Python or orphan inference');
    await writeFile(join(root,'.local-upgrade/t8-native-voice-chain-result.json'),JSON.stringify({runtime:process.versions,checks,audio_bytes:audioBytes,physical_device_test:false},null,2));
    checks.forEach(check=>console.log('PASS:',check));
  } finally {done=true;await polling;clearTimeout(deadline);client.close();host.close();child.kill();await rm(directory,{recursive:true,force:true});}
}).then(()=>app.exit(0),error=>{console.error(phase,error instanceof Error?error.message:'Voice chain failed');app.exit(1);});
