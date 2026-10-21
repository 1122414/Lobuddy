import { join } from 'node:path';
import { mkdirSync, lstatSync } from 'node:fs';
import { ServiceConnectSchema, type ServiceEvent } from '@lobuddy/contracts';
import { createStorageService } from './storage-service.js';
import { TaskCoordinator } from './tasks/coordinator.js';
import { ImageStore } from './tools/images.js';
import { DshRuntime, type Engine } from './engine/runtime.js';
import { RpcFault } from './fault.js';
import type { Handlers } from './rpc-server.js';
import { KnowledgeService } from './knowledge/service.js';
import { createCompanionServices } from './companion-service.js';

export async function createApplicationService(input: unknown, publish: (event: ServiceEvent) => void,
  engineFactory?: () => Engine) {
  const options = ServiceConnectSchema.parse(input);
  if (!options.storage) throw new RpcFault('invalid_request');
  const storage = createStorageService(options.storage);
  let tasks: TaskCoordinator | undefined;
  let companion: Awaited<ReturnType<typeof createCompanionServices>> | undefined;
  try {
    if (options.storage.create) mkdirSync(options.storage.workspace, { recursive: true, mode: 0o700 });
    if (!lstatSync(options.storage.workspace).isDirectory()) throw new RpcFault('unavailable');
    const images = new ImageStore(join(options.storage.data, 'images'));
    const engine = options.engine;
    storage.settings.setCredentialStatus({ llm_api_key: Boolean(engine?.apiKey) });
    const configured = Boolean(engine || engineFactory);
    const knowledge = new KnowledgeService(storage.store, () => storage.settings.effective());
    const coordinator: TaskCoordinator = tasks = new TaskCoordinator({ store: storage.store, settings: () => storage.settings.effective(),
      images, applicationRoot: engine?.applicationRoot ?? process.cwd(), publish,
      context: state => knowledge.prepare(state),
      knowledge: (...args) => knowledge.tools(coordinator.approvals)(...args),
      beforeStart: state => companion?.beforeStart(state), settled: state => companion?.settled(state),
      engine: engineFactory ?? (() => {
        if (!engine) throw new RpcFault('unavailable');
        return new DshRuntime({ ...engine, home: join(options.storage!.data, 'dsh'), workspace: options.storage!.workspace });
      }) });
    companion = await createCompanionServices(storage.store, () => storage.settings.effective(), images, knowledge, coordinator);
    const companionship = companion;
    const handlers: Handlers = { ...storage.handlers, ...companionship.handlers,
      'settings.patch': async params => {
        await companionship.learning.activity();
        const result = storage.settings.patch(params); knowledge.bootstrap(); return result;
      },
      'service.health': () => ({ protocol: 2, engine: configured ? 'dsh' : 'ts-unconfigured',
        connected: coordinator.connected, voice_available: false, model_configured: configured }),
      'turn.send': async (params, context) => {
        if (!configured) throw new RpcFault('unavailable');
        await companionship.learning.activity(); companionship.start();
        return coordinator.submit(context.requestId, params);
      },
      'turn.cancel': params => coordinator.cancel(params.turn_id),
      'task.list': () => coordinator.turns.list(), 'task.get': params => coordinator.turns.get(params.turn_id),
      'task.outcome': params => coordinator.ledger.outcomes.get(params.turn_id),
      'approval.list': () => coordinator.approvals.list(),
      'approval.resolve': params => ({ accepted: coordinator.approvals.resolve(params.approval_id, params.approved) }),
      'progress.get': () => coordinator.ledger.summary(),
      'image.import': params => images.importFile(params.path), 'image.get': params => images.get(params.image_id),
    };
    companionship.start();
    let closing: Promise<void> | undefined;
    return { handlers, tasks: coordinator, store: storage.store, close: () => closing ??= (async () => {
      await companionship.close(); await coordinator.close(); storage.close();
    })() };
  } catch (error) { await companion?.close(); await tasks?.close(); storage.close(); throw error; }
}
