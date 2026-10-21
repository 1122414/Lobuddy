import { app,MessageChannelMain } from 'electron';
import { resolve,join } from 'node:path';
import { readFile,writeFile } from 'node:fs/promises';
import { setTimeout as delay } from 'node:timers/promises';
import assert from 'node:assert/strict';
void app.whenReady().then(async () => {
  const root = resolve(__dirname,'../../..');
  const { hostSpeech } = await import('@lobuddy/speech/electron');
  const { SpeechClient } = await import('@lobuddy/speech'); const { portTransport } = await import('@lobuddy/service');
  const { port1,port2 } = new MessageChannelMain(),host = hostSpeech(port2,join(root,'.local-upgrade/ts-assets'));
  const client = new SpeechClient(portTransport(port1,'electron')); const checks: string[] = [];
  const events: { kind: string; generation: number; round: number; text: string }[] = [];
  client.event = event => events.push(event); client.fault = () => {};
  const deadline = setTimeout(() => { host.close(); app.exit(1); },120000);
  try {
    assert.equal(await client.request({ kind: 'check' }),true); checks.push('fixed hashes verified in isolated Electron speech utility');
    await client.request({ kind: 'start',generation: 1,silence_ms: 700 });
    const { pcm16Mono } = await import('./speech-probe.js');
    const wave = process.env.LOBUDDY_PROBE_WAV;
    if (!wave) throw Error('Explicit synthetic wave required');
    const audio = pcm16Mono(await readFile(wave));
    const started = performance.now();
    for (let offset = 0; offset < audio.length + 16000; offset += 512) {
      const buffer = Buffer.alloc(1024); for (let i = 0; i < 512; i++) buffer.writeInt16LE(Math.round(Math.max(-1,Math.min(.9999,audio[offset+i] ?? 0))*32768),i*2);
      await client.request({ kind: 'frame',generation: 1,pcm: buffer.toString('base64') });
    }
    while (!events.some(event => event.kind === 'transcript') && performance.now() - started < 60000) await delay(50);
    assert.ok(events.some(event => event.kind === 'speech')); const transcript = events.find(event => event.kind === 'transcript'); assert.ok(transcript?.text.trim());
    checks.push('real Silero recurrent state and Whisper small q8 transcribe local PCM without Python');
    const pid = host.pid; await client.request({ kind: 'stop' });
    for (let i=0;i<100;i++) { try { process.kill(pid!,0); await delay(20); } catch { break; } }
    assert.throws(() => process.kill(pid!,0)); checks.push('stop kills only the owned inference process without orphan');
    await client.request({ kind: 'start',generation: 2,silence_ms: 700 });
    process.kill(host.pid!,'SIGKILL'); await delay(100); await client.request({ kind: 'check' });
    checks.push('explicit request creates a fresh process after a forced inference crash');
    await writeFile(join(root,'.local-upgrade/t8-native-speech-process-result.json'),JSON.stringify({ runtime: process.versions,checks,characters: transcript!.text.length,elapsed_ms: performance.now()-started },null,2));
    checks.forEach(check => console.log('PASS:',check));
  } finally { clearTimeout(deadline); await client.close(); host.close(); }
}).then(() => app.exit(0),error => { console.error(error instanceof Error ? error.message : 'Voice probe failed'); app.exit(1); });
