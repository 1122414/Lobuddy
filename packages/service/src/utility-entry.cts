import type {} from 'electron';

const parent = process.parentPort;
if (!parent) throw new Error('Business service requires an explicit parent MessagePort');
parent.once('message', async event => {
  const port = event.ports[0];
  if (!port) { process.exitCode = 1; return; }
  const { RpcServer, portTransport } = await import('./index.js');
  const server = new RpcServer(portTransport(port, 'electron'), {
    // Only this capability is implemented at T2. Full business wiring arrives in T3–T8.
    'service.health': () => ({ protocol: 2, engine: 'ts-unconfigured', connected: false,
      voice_available: false, model_configured: false }),
  });
  port.on('close', () => { void server.close().then(() => process.exit(0), () => process.exit(1)); });
});
