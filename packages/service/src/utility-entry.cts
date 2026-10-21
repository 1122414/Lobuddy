import type {} from 'electron';

const parent = process.parentPort;
if (!parent) throw new Error('Business service requires an explicit parent MessagePort');
let phase = 'channel';
parent.once('message', event => {
  void (async () => {
    const port = event.ports[0];
    if (!port) throw new Error('Missing service channel');
    phase = 'contracts';const { ServiceConnectSchema } = await import('@lobuddy/contracts');
    const options = ServiceConnectSchema.parse(event.data);
    phase = 'modules';const { RpcServer, portTransport } = await import('./index.js');
    const { createApplicationService } = await import('./application-service.js');
    const { SpeechClient } = await import('@lobuddy/speech');
    const speech = event.ports[1] ? new SpeechClient(portTransport(event.ports[1], 'electron')) : undefined;
    let server: InstanceType<typeof RpcServer>;
    phase = 'storage';const service = options.storage ? await createApplicationService(options, event => server.publish(event),undefined,speech) : undefined;
    phase = 'server';
    server = new RpcServer(portTransport(port, 'electron'), service?.handlers ?? {
      'service.health': () => ({ protocol: 2, engine: 'ts-unconfigured', connected: false,
        voice_available: false, model_configured: false }),
    }, async () => service?.close());
    port.on('close', () => { void server.close().then(() => process.exit(0), () => process.exit(1)); });
  })().catch(error => {
    const code = ['ERR_MODULE_NOT_FOUND','MODULE_NOT_FOUND','ERR_DLOPEN_FAILED'].includes(error?.code) ? error.code : 'STARTUP_FAILED';
    process.stderr.write(`LOBUDDY_STARTUP:${phase}:${code}\n`);process.exit(1);
  });
});
