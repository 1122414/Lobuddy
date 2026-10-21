import { join } from 'node:path';
import { mkdirSync, lstatSync } from 'node:fs';
import { ServiceConnectSchema, type ServiceEvent } from '@lobuddy/contracts';
import { createStorageService } from './storage-service.js';
import { TaskCoordinator } from './tasks/coordinator.js';
import { ImageStore } from './tools/images.js';
import { DshRuntime, type Engine } from './engine/runtime.js';
import { RpcFault } from './fault.js';
import type { Handlers } from './rpc-server.js';

export function createApplicationService(input: unknown, publish: (event: ServiceEvent) => void,
  engineFactory?: () => Engine) {
  const options = ServiceConnectSchema.parse(input);
  if (!options.storage) throw new RpcFault('invalid_request');
  const storage = createStorageService(options.storage);
  try {
    if (options.storage.create) mkdirSync(options.storage.workspace, { recursive: true, mode: 0o700 });
    if (!lstatSync(options.storage.workspace).isDirectory()) throw new RpcFault('unavailable');
    const images = new ImageStore(join(options.storage.data, 'images'));
    const engine = options.engine;
    storage.settings.setCredentialStatus({ llm_api_key: Boolean(engine?.apiKey) });
    const configured = Boolean(engine || engineFactory);
    const tasks = new TaskCoordinator({ store: storage.store, settings: () => storage.settings.effective(),
      images, applicationRoot: engine?.applicationRoot ?? process.cwd(), publish,
      engine: engineFactory ?? (() => {
        if (!engine) throw new RpcFault('unavailable');
        return new DshRuntime({ ...engine, home: join(options.storage!.data, 'dsh'), workspace: options.storage!.workspace });
      }) });
    const handlers: Handlers = { ...storage.handlers,
      'service.health': () => ({ protocol: 2, engine: configured ? 'dsh' : 'ts-unconfigured',
        connected: tasks.connected, voice_available: false, model_configured: configured }),
      'turn.send': (params, context) => {
        if (!configured) throw new RpcFault('unavailable');
        return tasks.submit(context.requestId, params);
      },
      'turn.cancel': params => tasks.cancel(params.turn_id),
      'task.list': () => tasks.turns.list(), 'task.get': params => tasks.turns.get(params.turn_id),
      'task.outcome': params => tasks.ledger.outcomes.get(params.turn_id),
      'approval.list': () => tasks.approvals.list(),
      'approval.resolve': params => ({ accepted: tasks.approvals.resolve(params.approval_id, params.approved) }),
      'progress.get': () => tasks.ledger.summary(),
      'image.import': params => images.importFile(params.path), 'image.get': params => images.get(params.image_id),
    };
    let closing: Promise<void> | undefined;
    return { handlers, tasks, store: storage.store, close: () => closing ??= (async () => {
      await tasks.close(); storage.close();
    })() };
  } catch (error) { storage.close(); throw error; }
}
