import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp,rm } from 'node:fs/promises';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { VoiceService } from './voice/service.js';
import { spokenText,FishError,type Synthesizer } from './voice/fish.js';
import { Store } from './storage/database.js';
import { TurnStateSchema } from '@lobuddy/contracts';
import type { SpeechDriver,SpeechEvent,SpeechCommand } from '@lobuddy/speech';
class Driver implements SpeechDriver {
  event = (_event: SpeechEvent) => {}; fault = () => {};
  generation = 0; stops = 0; closed = false;
  request = async (command: SpeechCommand) => { if (command.kind === 'start') this.generation = command.generation; if (command.kind === 'stop') this.stops++; return true; };
  close = async () => { this.closed = true; };
  emit(kind: SpeechEvent['kind'],round: number,text = '',generation = this.generation) { this.event({ kind,round,text,generation }); }
}
const until = async (predicate: () => boolean) => { for (let i=0;i<200;i++) { if (predicate()) return; await delay(10); } throw Error('Voice predicate timed out'); };
async function fixture(tts?: Synthesizer,now?: () => number,cancelFails = false) {
  const root = await mkdtemp('/private/tmp/lobuddy-voice-ts-'),store = new Store(join(root,'data.db'),{ create: true }),driver = new Driver();
  const submissions: { id: string; text: string }[] = [],cancelled: string[] = [];
  const voice = new VoiceService(store,driver,() => 'synthetic-key',{
    submit: async (_session,text,id) => { submissions.push({ id,text }); return TurnStateSchema.parse({ turn_id: id,task_id: id,session_id: 's',engine_id: 'e',lane: 'foreground',status: 'running',input_text: text }); },
    cancel: async id => { cancelled.push(id); if (cancelFails) throw Error('provider offline'); },prepare: async () => {},
  },tts ?? (async function* () { yield Buffer.alloc(4096); }),now);
  await voice.initialize();
  return { voice,driver,submissions,cancelled,store,close: async () => { await voice.close(); store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('ten continuous voice rounds submit final transcripts and stream only user-facing answers with fixed voice options',async () => {
  const said: string[] = [],f = await fixture(async function* (text,_key,model) { assert.equal(model,'s2.1-pro-free'); said.push(text); yield Buffer.alloc(4096); });
  try {
    const status = f.voice.start('s'); assert.equal(status.state,'loading'); await until(() => f.voice.view().state === 'listening');
    let cursor = 0;
    for (let round=1;round<=10;round++) {
      f.driver.emit('speech',round); f.driver.emit('transcript',round,'你好' + round);
      await until(() => f.submissions.length === round); await delay(1);
      const id = f.submissions.at(-1)!.id;
      f.voice.turnEvent(id,'reasoning.delta','不该朗读'); f.voice.turnEvent(id,'tool.request','不该朗读');
      f.voice.turnEvent(id,'text.final','你好。```js\nsecret();\n```');
      f.voice.turnEvent(id,'turn.completed','你好。```js\nsecret();\n```');
      await until(() => f.voice.poll({ voice_id: status.voice_id,after: cursor,playing: false }).events.some(event => event.kind === 'audio.end'));
      const result = f.voice.poll({ voice_id: status.voice_id,after: cursor,playing: false });
      assert.ok(result.events.some(event => event.kind === 'audio' && event.round_id === round)); cursor = result.events.at(-1)!.sequence;
    }
    assert.equal(f.submissions.length,10); assert.ok(said.every(text => !/secret|不该/.test(text))); assert.equal(said.length,10);
    await f.voice.stop(); assert.equal(f.voice.view().state,'off'); assert.ok(f.driver.stops); assert.equal(f.voice.active,false);
  } finally { await f.close(); }
});
test('barge-in cancels only owned foreground turn and rejects late PCM/transcripts; mute changes generation and permits a fresh round',async () => {
  let release!: () => void;
  const blocked = new Promise<void>(resolve => { release = resolve; });
  const f = await fixture(async function* () { await blocked; yield Buffer.alloc(1024); });
  try {
    const { voice_id } = f.voice.start('s'); await until(() => f.voice.view().state === 'listening');
    f.driver.emit('speech',1); f.driver.emit('transcript',1,'第一句'); f.driver.emit('transcript',1,'重复事件'); await until(() => f.submissions.length === 1); await delay(1);
    f.voice.turnEvent(f.submissions[0]!.id,'text.final','等待音频。'); await delay(25);
    f.driver.emit('speech',2); f.driver.emit('transcript',1,'过期文字'); release(); await delay(30);
    const events = f.voice.poll({ voice_id,after: 0,playing: true }).events;
    assert.deepEqual(events.map(event => event.kind),['interrupt']); assert.deepEqual(f.cancelled,[f.submissions[0]!.id]); assert.equal(f.submissions.length,1);
    const prior = f.driver.generation; await f.voice.mute(voice_id,true);
    f.driver.emit('transcript',2,'静音后过期文字',prior); assert.equal(f.voice.view().state,'muted');
    assert.equal((await f.voice.frame({ voice_id,sequence: 1,pcm: Buffer.alloc(1024).toString('base64') })).accepted,false);
    await f.voice.mute(voice_id,false); await until(() => f.voice.view().state === 'listening'); assert.ok(f.driver.generation > prior);
    f.driver.emit('speech',1); f.driver.emit('transcript',1,'恢复的新一句'); await until(() => f.submissions.length === 2);
    assert.notEqual(f.submissions[0]!.id,f.submissions[1]!.id);
  } finally { await f.close(); }
});
test('frame gaps, process faults and synthesis failures stop inference without dropping into a different voice',async () => {
  const f = await fixture(async function* () { throw new FishError('选定音色不可用，未更换音色'); });
  try {
    let { voice_id } = f.voice.start('s'); await until(() => f.voice.view().state === 'listening');
    const pcm = Buffer.alloc(1024).toString('base64'); assert.equal((await f.voice.frame({ voice_id,sequence: 1,pcm })).accepted,true);
    assert.equal((await f.voice.frame({ voice_id,sequence: 1,pcm })).accepted,false);
    assert.equal((await f.voice.frame({ voice_id,sequence: 3,pcm })).accepted,false); assert.equal(f.voice.view().state,'error');
    await f.voice.stop(); ({ voice_id } = f.voice.start('s')); await until(() => f.voice.view().state === 'listening');
    f.driver.fault(); assert.equal(f.voice.view().state,'error'); assert.ok(f.driver.stops);
    await f.voice.stop(); ({ voice_id } = f.voice.start('s')); await until(() => f.voice.view().state === 'listening');
    f.driver.emit('speech',1); f.driver.emit('transcript',1,'测试'); await until(() => f.submissions.length === 1); await delay(1);
    f.voice.turnEvent(f.submissions[0]!.id,'text.final','回应。'); await until(() => f.voice.view().state === 'error');
    assert.match(f.voice.view().error,/未更换音色/); assert.equal(f.voice.view().reference_id,'e4a66454f7a44f63a2cc9e8c044d701d');
    assert.throws(() => f.voice.poll({ voice_id: 'stale',after: 0,playing: false }));
    assert.throws(() => f.voice.poll({ voice_id,after: 9000,playing: false }));
  } finally { await f.close(); }
});
test('stop during preparation invalidates late startup and restarting waits for the owned transition',async () => {
  const f = await fixture(); let release!: () => void;
  f.driver.request = async command => { if (command.kind === 'start') await new Promise<void>(resolve => { release = resolve; }); return true; };
  try {
    f.voice.start('s'); await until(() => Boolean(release)); const stopping = f.voice.stop();
    assert.throws(() => f.voice.start('s')); release(); await stopping;
    assert.equal(f.voice.view().state,'off'); assert.equal(f.voice.view().voice_id,'');
  } finally { await f.close(); }
});
test('speech text strips code, markdown image data and formatting but preserves user-facing link labels',() => {
  assert.equal(spokenText('你好 **世界** [资料](https://example.com) ![图](data:image/test) `code`\n```secret'), '你好 世界 资料');
  assert.equal(spokenText('***'), '');
});
test('lost client lease releases owned resources even if provider cancellation fails',async () => {
  let now = 0; const f = await fixture(undefined,() => now,true);
  try {
    f.voice.start('s'); await until(() => f.voice.view().state === 'listening');
    f.driver.emit('speech',1); f.driver.emit('transcript',1,'正在说话'); await until(() => f.submissions.length === 1); await delay(1);
    now = 6000; await until(() => !f.voice.active); await until(() => f.driver.stops > 0);
    assert.deepEqual(f.cancelled,[f.submissions[0]!.id]); assert.equal(f.voice.view().state,'off');
  } finally { await f.close(); }
});
test('preferences survive restart; missing models never start a download implicitly and PCM is absent from stored settings',async () => {
  const f = await fixture();
  try {
    f.voice.configure({fish_model:'s2.1-pro',silence_ms:900});
    const calls: string[] = []; f.driver.request = async command => {calls.push(command.kind);return false;};
    const next = new VoiceService(f.store,f.driver,()=>'',{submit:async()=>{throw Error('unexpected');},cancel:async()=>{},prepare:async()=>{}});
    await next.initialize(); assert.equal(next.view().silence_ms,900); assert.equal(next.view().fish_model,'s2.1-pro');
    assert.equal(next.start('s').voice_id,''); assert.deepEqual(calls,['check']);
    assert.equal(f.store.connection.prepare("SELECT count(*) n FROM app_settings WHERE value LIKE '%pcm%'").get()!.n,0);
    await next.close();
  } finally {await f.close();}
});
test('Fish reports API credit status without retry or provider detail; odd network chunks retain complete PCM frames',async () => {
  const { fishSynthesizer } = await import('./voice/fish.js'); let calls=0,destroyed=false;
  const denied = fishSynthesizer(async(body,key,model) => {
    calls++; assert.equal(key,'synthetic');assert.equal(model,'s2.1-pro');
    assert.equal(JSON.parse(body.toString()).reference_id,'e4a66454f7a44f63a2cc9e8c044d701d');
    return {statusCode:402,destroy:()=>{destroyed=true;},async *[Symbol.asyncIterator](){yield Buffer.from('private upstream details');}};
  });
  await assert.rejects(async()=>{for await(const _chunk of denied('你好','synthetic','s2.1-pro',new AbortController().signal)){assert.fail('No PCM expected');}},/独立于网页积分/);
  assert.equal(calls,1);assert.equal(destroyed,true);
  const expected=Buffer.alloc(5000,7),received:Buffer[]=[];
  const streaming=fishSynthesizer(async()=>({statusCode:200,destroy:()=>{},async *[Symbol.asyncIterator](){yield expected.subarray(0,1);yield expected.subarray(1,4097);yield expected.subarray(4097);}}));
  for await(const chunk of streaming('你好','synthetic','s2.1-pro-free',new AbortController().signal)){assert.equal(chunk.length%2,0);received.push(chunk);}
  assert.deepEqual(Buffer.concat(received),expected);
  const broken=fishSynthesizer(async()=>({statusCode:200,destroy:()=>{},async *[Symbol.asyncIterator](){yield Buffer.alloc(3);}}));
  await assert.rejects(async()=>{for await(const _chunk of broken('你好','synthetic','s2.1-pro-free',new AbortController().signal)){assert.fail('Incomplete sample');}},/完整音频/);
});
test('slow playback backpressures PCM without retaining unbounded audio or persisting frames',async()=>{
  const f=await fixture(async function*(){for(let i=0;i<200;i++)yield Buffer.alloc(4096);});
  try{
    const {voice_id}=f.voice.start('s');await until(()=>f.voice.view().state==='listening');
    f.driver.emit('speech',1);f.driver.emit('transcript',1,'你好');await until(()=>f.submissions.length===1);await delay(1);
    f.voice.turnEvent(f.submissions[0]!.id,'text.final','回答。');f.voice.turnEvent(f.submissions[0]!.id,'turn.completed','回答。');
    await delay(50);const first=f.voice.poll({voice_id,after:0,playing:false});assert.ok(first.events.length<=96);assert.equal(first.events.filter(e=>e.kind==='audio').length,94);
    let cursor=0,count=0,finished=false;
    for(let i=0;i<100&&!finished;i++){
      const result=f.voice.poll({voice_id,after:cursor,playing:false});assert.ok(result.events.length<=96);
      for(const event of result.events){cursor=event.sequence;if(event.kind==='audio')count++;if(event.kind==='audio.end')finished=true;}
      await delay(10);
    }
    assert.equal(count,200);assert.equal(finished,true);
    assert.equal(f.store.connection.prepare("SELECT count(*) n FROM app_settings WHERE value LIKE '%pcm%'").get()!.n,0);
  }finally{await f.close();}
});
