const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

async function controller(request, permission = async () => true) {
  const { transformWithOxc } = await import('vite');
  const updates = [], timers = [], exports = {};
  const code = (await transformWithOxc(readFileSync(resolve(__dirname, '../src/voice.ts'), 'utf8'), 'voice.ts')).code
    .replace(/import \{ request \} from ['"]\.\/api['"];?/, "const { request } = require('./api');")
    .replace('export class VoiceController', 'class VoiceController') + '\nexports.VoiceController = VoiceController;';
  vm.runInNewContext(code, {
    btoa: value => Buffer.from(value, 'binary').toString('base64'),
    exports, require: () => ({ request }), window: { lobuddy: { voicePermission: permission } },
    setTimeout: callback => { timers.push(callback); return timers.length; }, clearTimeout: () => {},
  });
  return { voice: new exports.VoiceController((...value) => updates.push(value)), updates, timers };
}

test('ending while OS permission is pending never starts voice afterward', async () => {
  const permission = deferred(), calls = [];
  const { voice } = await controller(async method => { calls.push(method); }, () => permission.promise);
  const starting = voice.start('chat');
  await voice.stop();
  permission.resolve(true);
  await starting;
  assert.deepEqual(calls, ['voice.stop']);
  assert.equal(voice.alive, false);
});

test('late listening response after mute cannot acquire microphone or play audio', async () => {
  const late = deferred(), muting = deferred();
  let polls = 0, microphones = 0, audio = 0;
  const { voice } = await controller(async method => {
    if (method === 'voice.poll') return ++polls === 1 ? late.promise : { status: { state: 'muted' }, events: [] };
    if (method === 'voice.mute') return muting.promise;
  });
  voice.alive = true; voice.voice = 'voice';
  voice.microphone = async () => { microphones++; };
  voice.play = () => { audio++; };
  const polling = voice.poll();
  const muted = voice.mute(true);
  late.resolve({ status: { state: 'listening' }, events: [{ voice_id: 'voice', sequence: 1, round_id: 1, kind: 'audio', pcm: 'AAA=' }] });
  await polling;
  muting.resolve({ state: 'muted' });
  await muted;
  assert.equal(microphones, 0);
  assert.equal(audio, 0);
  assert.equal(voice.muted, true);
});

test('resuming waits for the backend before reopening the microphone', async () => {
  const resumed = deferred();
  let microphones = 0;
  const { voice } = await controller(async method => {
    if (method === 'voice.mute') return resumed.promise;
    if (method === 'voice.poll') return { status: { state: 'listening' }, events: [] };
  });
  voice.alive = true; voice.voice = 'voice'; voice.muted = true;
  voice.microphone = async () => { microphones++; };
  const resuming = voice.mute(false);
  assert.equal(voice.muted, true);
  assert.equal(microphones, 0);
  resumed.resolve({ state: 'listening' });
  await resuming;
  assert.equal(microphones, 1);
  assert.equal(voice.muted, false);
});

test('old poll failure cannot stop a newly started voice session', async () => {
  const old = deferred(), calls = [];
  const { voice } = await controller(async method => {
    calls.push(method);
    if (method === 'voice.poll') return calls.filter(value => value === method).length === 1 ? old.promise : { status: { state: 'loading' }, events: [] };
    if (method === 'voice.start') return { voice_id: 'new', state: 'loading' };
  });
  voice.alive = true; voice.voice = 'old';
  const polling = voice.poll();
  await voice.stop();
  await voice.start('chat');
  old.reject(Error('old connection closed'));
  await polling;
  assert.equal(voice.alive, true);
  assert.equal(voice.voice, 'new');
  assert.equal(calls.filter(value => value === 'voice.stop').length, 1);
});


test('a short burst of capture frames drains in order without ending continuous voice', async () => {
  const first = deferred(), sequences = [], calls = [];
  const { voice } = await controller(async (method, params) => {
    calls.push(method);
    if (method === 'voice.frame') {
      sequences.push(params.sequence);
      if (params.sequence === 1) await first.promise;
    }
  });
  voice.alive = true; voice.voice = 'voice';
  for (let i = 0; i < 16; i++) voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  const queue = voice.captureQueue;
  assert.equal(voice.alive, true);
  assert.equal(queue.pending, 16);
  first.resolve(); await queue.tail;
  assert.deepEqual(sequences, Array.from({ length: 16 }, (_, i) => i + 1));
  assert.equal(queue.pending, 0);
  assert.ok(!calls.includes('voice.stop'));
});

test('sustained capture overload stays bounded and releases the voice owner', async () => {
  const stalled = deferred(), calls = [];
  const { voice } = await controller(async method => {
    calls.push(method);
    if (method === 'voice.frame') await stalled.promise;
  });
  voice.alive = true; voice.voice = 'voice';
  voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  await Promise.resolve();
  const queue = voice.captureQueue;
  for (let i = 1; i < 32; i++) voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  assert.equal(queue.pending, 32);
  voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  assert.equal(voice.alive, false);
  assert.equal(queue.pending, 32);
  assert.equal(voice.captureQueue.pending, 0);
  stalled.resolve(); await queue.tail;
  assert.equal(queue.pending, 0);
  assert.equal(calls.filter(method => method === 'voice.frame').length, 1);
  assert.equal(calls.filter(method => method === 'voice.stop').length, 1);
});

test('a stopped generation cannot block or decrement a replacement capture queue', async () => {
  const old = deferred(), calls = [];
  const { voice } = await controller(async (method, params) => {
    if (method === 'voice.frame') {
      calls.push(params.voice_id);
      if (params.voice_id === 'old') await old.promise;
    }
  });
  voice.alive = true; voice.voice = 'old';
  voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  await Promise.resolve();
  const previous = voice.captureQueue;
  await voice.stop();
  voice.alive = true; voice.voice = 'new'; voice.frame = 0;
  voice.captureFrame(new ArrayBuffer(1024), voice.generation);
  const current = voice.captureQueue;
  await current.tail;
  assert.deepEqual(calls, ['old', 'new']);
  old.resolve(); await previous.tail;
  assert.equal(current.pending, 0);
  assert.equal(voice.alive, true);
});
