import { utilityProcess,type MessagePortMain,type UtilityProcess } from 'electron';
import { fileURLToPath } from 'node:url';
import { SpeechRequestSchema,SpeechReplySchema } from './protocol.js';
/** Main owns the speech process. It receives no provider keys and accepts no renderer paths. */
export function hostSpeech(port: MessagePortMain,root: string) {
  let child: UtilityProcess | undefined,closed = false;
  const pending = new Set<string>();
  let booted = false,queued: unknown[] = [],bootTimer: ReturnType<typeof setTimeout> | undefined;
  const send = (packet: unknown) => { if (!closed) port.postMessage(packet); };
  const stop = () => {
    const old = child; child = undefined; booted = false; queued = []; clearTimeout(bootTimer); old?.kill();
    for (const id of pending) send({ kind: 'reply',id,ok: false,ready: false }); pending.clear();
  };
  const spawn = () => {
    if (child) return child;
    const owned = utilityProcess.fork(fileURLToPath(new URL('./utility-entry.cjs',import.meta.url)),[],{
      stdio: 'pipe',serviceName: 'Lobuddy local speech',env: { PATH: '/usr/bin:/bin',HOME: process.env.HOME,HF_HUB_DISABLE_TELEMETRY: '1',ORT_DISABLE_TELEMETRY: '1' },
    });
    child = owned; owned.stdout?.on('data',() => {}); owned.stderr?.on('data',() => {});
    bootTimer = setTimeout(() => { if (child === owned && !booted) { stop(); send({ kind: 'fault' }); } },10000);
    owned.on('message',raw => {
      if (child !== owned) return;
      const parsed = SpeechReplySchema.safeParse(raw); if (!parsed.success) { stop(); send({ kind: 'fault' }); return; }
      if (parsed.data.kind === 'booted') { booted = true; clearTimeout(bootTimer); for (const request of queued) owned.postMessage(request); queued = []; return; }
      if (parsed.data.kind === 'reply') pending.delete(parsed.data.id); send(parsed.data);
    });
    owned.on('exit',() => { if (child === owned) { child = undefined; booted = false; queued = []; clearTimeout(bootTimer); pending.clear(); send({ kind: 'fault' }); } });
    owned.postMessage({ root }); return owned;
  };
  port.on('message',packet => {
    const result = SpeechRequestSchema.safeParse(packet.data);
    if (!result.success || closed) { stop(); send({ kind: 'fault' }); return; }
    const request = result.data;
    // Killing owned inference guarantees that mute/end does not wait for a long ASR run.
    if (request.command.kind === 'stop') { stop(); send({ kind: 'reply',id: request.id,ok: true,ready: false }); return; }
    if (pending.size >= 40) { stop(); send({ kind: 'fault' }); return; }
    try { pending.add(request.id); const owned = spawn(); if (booted) owned.postMessage(request); else queued.push(request); } catch { stop(); send({ kind: 'fault' }); }
  });
  port.on('close',() => { closed = true; stop(); }); port.start();
  return { close: () => { closed = true; stop(); port.close(); },get pid() { return child?.pid; } };
}
