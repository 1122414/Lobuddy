import { parentPort, workerData } from 'node:worker_threads';
import { ServiceConnectSchema } from '@lobuddy/contracts';
import { RpcServer, type Handlers } from './rpc-server.js';
import { portTransport } from './transport.js';
import { createStorageService } from './storage-service.js';

if (!parentPort) throw new Error('Node host requires an explicit MessagePort');
const options = ServiceConnectSchema.parse(workerData ?? { kind: 'connect' });
const service = options.storage ? createStorageService(options.storage) : undefined;
const health: Handlers = { 'service.health': () => ({ protocol: 2, engine: 'ts-unconfigured', connected: false,
  voice_available: false, model_configured: false }) };
new RpcServer(portTransport(parentPort, 'node'), service?.handlers ?? health, async () => service?.close());
