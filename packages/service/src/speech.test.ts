import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { mkdtemp,rm,readdir } from 'node:fs/promises';
import { AudioSession,modelsReady,downloadModels,SpeechClient,type AudioRecognizer,type SpeechEvent } from '@lobuddy/speech';
import { MessageChannel } from 'node:worker_threads';
import { portTransport } from './transport.js';
const pcm = (value: number) => { const bytes = Buffer.alloc(1024); for (let i=0;i<512;i++) bytes.writeInt16LE(value,i*2); return bytes.toString('base64'); };
const until = async (predicate: () => boolean) => { for(let i=0;i<200;i++) { if(predicate())return; await delay(5); } throw Error('Speech predicate timed out'); };
test('VAD retains preroll, ends after configured silence and transcribes ten bounded continuous utterances',async () => {
  const events: SpeechEvent[] = []; let closed = false;
  const engine: AudioRecognizer = { probability: async data => data[0]! > .1 ? .9 : .01,
    transcribe: async audio => { assert.ok(audio.length <= 938*512); return '最终转写'; },close: async () => { closed = true; } };
  const session = new AudioSession(engine,700,1,event => events.push(event));
  for (let i=0;i<10;i++) {
    for(let n=0;n<3;n++) await session.frame(pcm(10000));
    for(let n=0;n<22;n++) await session.frame(pcm(0));
    await until(() => events.filter(event => event.kind === 'transcript').length === i+1);
  }
  assert.equal(events.filter(event => event.kind === 'speech').length,10); assert.equal(events.at(-1)!.round,10);
  await session.close(); assert.equal(closed,true); await assert.rejects(session.frame(pcm(0)));
});
test('ASR does not block speech-start detection, late transcript is discarded and a second pending utterance fails boundedly',async () => {
  const events: SpeechEvent[] = []; let finish!: (text: string) => void;
  const engine: AudioRecognizer = { probability: async data => data[0]! > .1 ? .9 : .01,
    transcribe: () => new Promise(resolve => { finish = resolve; }),close: async () => {} };
  const session = new AudioSession(engine,300,3,event => events.push(event));
  for(let n=0;n<3;n++) await session.frame(pcm(10000)); for(let n=0;n<10;n++) await session.frame(pcm(0));
  for(let n=0;n<3;n++) await session.frame(pcm(10000));
  assert.equal(events.filter(event => event.kind === 'speech').length,2);
  for(let n=0;n<10;n++) await session.frame(pcm(0)); assert.equal(events.at(-1)!.kind,'overload');
  finish('不得发送'); await session.close(); assert.ok(!events.some(event => event.kind === 'transcript'));
});
test('capture queue rejects sustained overload; malformed PCM never reaches VAD',async () => {
  let release!: () => void;
  const engine: AudioRecognizer = { probability: async () => { await new Promise<void>(resolve => { release = resolve; }); return 0; },transcribe: async () => '',close: async () => {} };
  const events: SpeechEvent[] = [],session = new AudioSession(engine,700,1,event => events.push(event));
  await assert.rejects(session.frame('invalid')); const pending = Array.from({ length:32 },() => session.frame(pcm(0)));
  await until(() => Boolean(release)); await assert.rejects(session.frame(pcm(0)),/队列/); release(); await Promise.all(pending); await session.close(); assert.equal(events.at(-1)!.kind,'overload');
});
test('model readiness cannot be asserted by a marker and failed download removes partial files without cloud fallback',async () => {
  const root = await mkdtemp('/private/tmp/lobuddy-speech-models-'); const original = globalThis.fetch;
  try {
    assert.equal(await modelsReady(root),false); globalThis.fetch = async () => new Response('bad asset');
    await assert.rejects(downloadModels(root,new AbortController().signal),/校验/);
    assert.equal(await modelsReady(root),false); assert.deepEqual(await readdir(root+'/whisper-small'),[]);
  } finally { globalThis.fetch = original; await rm(root,{ recursive: true,force: true }); }
});
test('speech channel bounds pending work, ignores late replies and reports a disconnected owner',async () => {
  const { port1,port2 } = new MessageChannel(),client = new SpeechClient(portTransport(port1,'node')); let fault = false;
  client.fault = () => { fault = true; }; const pending = client.request({ kind:'check' });
  port2.postMessage({ kind: 'fault' }); await assert.rejects(pending); assert.equal(fault,true);
  await client.close(); port2.close(); await assert.rejects(client.request({ kind:'check' }));
});
