import type {} from 'electron';
const parent = process.parentPort;
if (!parent) throw Error('Speech requires its owning main process');
parent.once('message',event => {
  void (async () => {
    const { z } = await import('zod');
    const root = z.strictObject({ root: z.string().min(1).max(4096) }).parse(event.data).root;
    const { SpeechRequestSchema } = await import('./protocol.js');
    const { modelsReady,downloadModels } = await import('./models.js');
    const { AudioSession,loadRecognizer } = await import('./recognizer.js');
    let session: InstanceType<typeof AudioSession> | undefined;
    let busy = false,ready = false;
    const lifetime = new AbortController();
    parent.on('message',packet => {
      void (async () => {
        const { id,command } = SpeechRequestSchema.parse(packet.data);
        try {
          if (command.kind === 'frame') {
            if (!session || session.generation !== command.generation) throw Error('Expired generation');
            await session.frame(command.pcm);
          } else {
            if (busy) throw Error('Busy'); busy = true;
            try {
              if (command.kind === 'check') ready = await modelsReady(root);
              if (command.kind === 'download') { if (session) throw Error('Listening'); await downloadModels(root,lifetime.signal); ready = true; }
              if (command.kind === 'start') {
                if (session || !await modelsReady(root)) throw Error('Missing verified model');
                const recognizer = await loadRecognizer(root); ready = true;
                session = new AudioSession(recognizer,command.silence_ms,command.generation,event => parent.postMessage({ kind: 'event',event }));
              }
              if (command.kind === 'stop') { const old = session; session = undefined; await old?.close(); }
            } finally { busy = false; }
          }
          parent.postMessage({ kind: 'reply',id,ok: true,ready });
        } catch { parent.postMessage({ kind: 'reply',id,ok: false,ready: false }); }
      })().catch(() => { parent.postMessage({ kind: 'fault' }); process.exit(1); });
    });
    parent.postMessage({ kind: 'booted' });
  })().catch(() => process.exit(1));
});
