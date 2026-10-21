import { parentPort } from 'node:worker_threads';
import { RpcServer } from './rpc-server.js';
import { portTransport } from './transport.js';

if (!parentPort) throw new Error('Node host requires an explicit MessagePort');
new RpcServer(portTransport(parentPort, 'node'), {
  'service.health': () => ({ protocol: 2, engine: 'ts-unconfigured', connected: false,
    voice_available: false, model_configured: false }),
});
