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
import { LocalScheduler } from './companion/scheduler.js';
import { resolveWallTime } from '@lobuddy/domain';
import { DelegationRecovery } from './tasks/recovery.js';

export async function createApplicationService(input: unknown, publish: (event: ServiceEvent) => void,
  engineFactory?: () => Engine) {
  const options = ServiceConnectSchema.parse(input);
  if (!options.storage) throw new RpcFault('invalid_request');
  const storage = createStorageService(options.storage);
  let tasks: TaskCoordinator | undefined;
  let companion: Awaited<ReturnType<typeof createCompanionServices>> | undefined;
  let scheduler: LocalScheduler | undefined;
  try {
    if (options.storage.create) mkdirSync(options.storage.workspace, { recursive: true, mode: 0o700 });
    if (!lstatSync(options.storage.workspace).isDirectory()) throw new RpcFault('unavailable');
    const images = new ImageStore(join(options.storage.data, 'images'));
    const engine = options.engine;
    storage.settings.setCredentialStatus({ ...Object.fromEntries(Object.entries(options.credentials ?? {}).map(([key,value]) => [key,Boolean(value)])),llm_api_key: Boolean(engine?.apiKey) });
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
    companion = await createCompanionServices(storage.store, () => storage.settings.effective(), images, knowledge, coordinator,
      id => scheduler?.repo.event('focus-' + id,'focus_finished'));
    const companionship = companion;
    const schedule = scheduler = new LocalScheduler(coordinator,companionship,() => storage.settings.effective(),() => ({
      key: options.credentials?.typesafe_api_key ?? '',secrets: [engine?.apiKey ?? '',...Object.values(options.credentials ?? {})],
    }));
    const delegations = schedule.delegations;
    const recovery = new DelegationRecovery(coordinator,() => storage.settings.effective());
    const handlers: Handlers = { ...storage.handlers, ...companionship.handlers,
      'schedule.get': p => schedule.repo.view(p.delegation_id),
      'schedule.resolve': p => ({ at: resolveWallTime(p.local,p.timezone) }),
      'runtime.power': async p => { await schedule.power(p.suspended); return { accepted: true }; },
      'notification.list': () => schedule.notifications.list(), 'jev.status': () => schedule.decisions.view(),
      'notification.next': () => { schedule.decisions.poll(); return schedule.notifications.next(schedule.quiet()); },
      'notification.displayed': p => { const accepted = schedule.notifications.displayed(p.batch_id,schedule.quiet()); schedule.repo.completeDeliveries(); return { accepted }; },
      'notification.read': p => { const result = schedule.notifications.read(p.notification_id); schedule.repo.completeDeliveries(); return result; },
      'delegation.list': () => delegations.repo.list(), 'delegation.get': p => delegations.detail(p.delegation_id),
      'delegation.create': (p,c) => { if (p.project_id) companionship.projects.scope(p.project_id,''); return delegations.repo.create(c.requestId,p); },
      'delegation.confirm': (p,c) => delegations.change(c.requestId,'confirm',p),
      'delegation.edit': (p,c) => delegations.change(c.requestId,'edit',p),
      'delegation.pause': (p,c) => delegations.change(c.requestId,'pause',p),
      'delegation.resume': (p,c) => delegations.change(c.requestId,'resume',p),
      'delegation.cancel': (p,c) => delegations.change(c.requestId,'cancel',p),
      'delegation.run': async (p,c) => { if (schedule.suspended) throw new RpcFault('unavailable'); await companionship.learning.activity(); return delegations.run(c.requestId,p); },
      'delegation.recover': async p => {
        if (schedule.suspended) throw new RpcFault('unavailable'); await companionship.learning.activity();
        recovery.recover(p); return delegations.detail(p.delegation_id);
      },
      'settings.patch': async params => {
        await companionship.learning.activity(); await schedule.decisions.stop();
        const result = storage.settings.patch(params); knowledge.bootstrap(); return result;
      },
      'service.health': () => ({ protocol: 2, engine: configured ? 'dsh' : 'ts-unconfigured',
        connected: coordinator.connected, voice_available: false, model_configured: configured }),
      'turn.send': async (params, context) => {
        if (schedule.suspended || !configured && !params.workflow_id) throw new RpcFault('unavailable');
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
    const companionTrigger = handlers['companionship.trigger']!;
    handlers['companionship.trigger'] = async (p,c) => {
      const result = await companionTrigger(p,c);
      if (p.event === 'app_returned') schedule.repo.event('returned-' + c.requestId,'app_returned'); return result;
    };
    companionship.start(); schedule.start();
    let closing: Promise<void> | undefined;
    return { handlers, tasks: coordinator, scheduler: schedule, store: storage.store, close: () => closing ??= (async () => {
      await schedule.close(); await companionship.close(); await coordinator.close(); storage.close();
    })() };
  } catch (error) { await scheduler?.close(); await companion?.close(); await tasks?.close(); storage.close(); throw error; }
}
