import { TurnStateSchema, TurnSendSchema, type TurnState, type TurnSend, type RuntimeSettings, type ServiceEvent, type BridgeEvent } from '@lobuddy/contracts';
import { TurnRepository } from '../storage/turns.js';
import { RuntimeLedger } from '../storage/ledger.js';
import { Store } from '../storage/database.js';
import { EngineError } from '../engine/transport.js';
import type { Engine } from '../engine/runtime.js';
import { Approvals } from './approvals.js';
import { GovernedTools, type KnowledgeTools } from '../tools/governed.js';
import { ImageStore } from '../tools/images.js';
import { RpcFault } from '../fault.js';
import { randomUUID } from 'node:crypto';
import { WorkflowRepository } from '../storage/workflows.js';
import { DelegationRepository } from '../storage/delegations.js';
import { WorkflowExecution } from './workflows.js';

type Job = { state: TurnState; abort: AbortController; result: Promise<TurnState['status']>;
  complete: (status: TurnState['status']) => void; fail: (error: unknown) => void;
  terminal: Promise<void>; stopped: () => void; submitted: boolean; tools?: GovernedTools; effects: Set<Promise<void>> };
export type CoordinatorOptions = {
  store: Store; settings: () => RuntimeSettings; engine: () => Engine; images: ImageStore;
  applicationRoot: string; publish: (event: ServiceEvent) => void;
  context?: (state: TurnState) => string | Promise<string>; knowledge?: KnowledgeTools;
  beforeStart?: (state: TurnState) => void; settled?: (state: TurnState) => void;
};
export class TaskCoordinator {
  readonly turns: TurnRepository;
  readonly ledger: RuntimeLedger;
  readonly approvals: Approvals;
  readonly workflows: WorkflowRepository;
  readonly delegations: DelegationRepository;
  readonly workflowExecution: WorkflowExecution;
  private readonly jobs = new Map<string, Job>();
  private readonly lanes: Record<TurnState['lane'], string[]> = { foreground: [], background: [] };
  private readonly processors = new Map<string, Promise<void>>();
  private engine?: Engine;
  private engineStarting?: Promise<void>;
  private restarting?: Promise<void>;
  private consumer?: Promise<void>;
  private engineFailed = false;
  private closed = false;
  private closing?: Promise<void>;
  constructor(private readonly options: CoordinatorOptions) {
    this.turns = new TurnRepository(options.store); this.ledger = new RuntimeLedger(options.store, this.turns);
    this.approvals = new Approvals((state, kind, data) => this.emit(state, kind, data));
    this.workflows = new WorkflowRepository(options.store); this.delegations = new DelegationRepository(options.store);
    this.workflowExecution = new WorkflowExecution(this.workflows,this.delegations,this.ledger.outcomes);
    this.ledger.recover();
    this.delegations.recover();
    this.workflows.recover();
  }
  get connected(): boolean { return this.engine?.connected ?? false; }
  async prepare(): Promise<void> { await this.ensureEngine(); }
  get busy(): boolean { return this.jobs.size > 0; }
  activeStates(): TurnState[] { return [...this.jobs.values()].map(job => TurnStateSchema.parse(job.state)); }
  async analyze(prompt: string, signal: AbortSignal, maxTokens: 1024 | 2048 = 1024, reasoningEffort?: 'off'): Promise<string> {
    signal.throwIfAborted(); await this.ensureEngine(); signal.throwIfAborted();
    const id = randomUUID();
    try {
      const result = await this.engine!.call('analysis.run', { id, prompt, maxTokens,...(reasoningEffort ? { reasoningEffort } : {}) }, signal);
      signal.throwIfAborted();
      if (!result || typeof result !== 'object' || !('text' in result) || typeof result.text !== 'string') throw Error('知识整理结果无效');
      return result.text;
    } finally { await this.engine!.call('analysis.cancel', { id }).catch(() => {}); }
  }
  private emit(state: TurnState, kind: string, data: ServiceEvent['data']): void {
    const event = this.options.store.transaction(() => this.turns.event(state, kind, data)); this.options.publish(event);
  }
  async submit(requestId: string, input: TurnSend, runId?: string): Promise<TurnState> {
    if (this.closed) throw new RpcFault('unavailable');
    const params = TurnSendSchema.parse(input);
    if (!params.text.trim()) throw new RpcFault('invalid_request');
    const version = params.workflow_id ? this.workflows.active(params.workflow_id) : undefined;
    const run = runId ? this.delegations.run(runId) : undefined;
    if (run && (!version || run.workflow_version !== version.version_id || !this.delegations.active(run.id))) throw new RpcFault('invalid_request');
    if (params.image_id) await this.options.images.get(params.image_id);
    if (this.closed) throw new RpcFault('unavailable');
    const result = this.turns.submit(requestId, params,state => {
      state.workflow_version = version?.version_id ?? '';
      if (run) {
        state.run_id = run.id; state.delegation_id = run.delegation_id;
        state.project_id = this.delegations.get(run.delegation_id).spec.project_id;
        this.delegations.bindWithinTransaction(run.id,state.turn_id);
      }
      if (!version) {
        try { this.workflows.begin(this.workflows.active('assistant-context').version_id,'context:' + state.turn_id); }
        catch { /* Disabled context workflow falls back to complete baseline serialization. */ }
      }
    });
    if (!result.created) return result.state;
    if (this.engineFailed && !this.jobs.size) {
      this.restarting ??= (async () => {
        await this.engine?.close(); await this.consumer;
        this.engine = undefined; this.engineStarting = undefined; this.engineFailed = false;
      })();
      try { await this.restarting; }
      catch {
        result.state.status = 'interrupted'; result.state.error = '无法确认旧引擎退出，未开始新任务。';
        for (const event of this.ledger.finish(result.state).events) this.options.publish(event);
        throw new RpcFault('unavailable');
      }
      finally { this.restarting = undefined; }
    }
    return this.enqueue(result.state);
  }
  resumeReadonly(id: string, authorize: (state: TurnState) => void): TurnState {
    if (this.closed || this.jobs.has(id)) throw new RpcFault('unavailable');
    const state = this.turns.get(id);
    if (!state.run_id || !state.workflow_version || !['cancelled','interrupted','failed'].includes(state.status)) throw new RpcFault('invalid_request');
    this.options.store.transaction(() => { authorize(state); state.status = 'queued'; state.error = ''; this.turns.save(state); });
    return this.enqueue(state);
  }
  private enqueue(state: TurnState): TurnState {
    let complete!: Job['complete'], fail!: Job['fail'];
    const promise = new Promise<TurnState['status']>((resolve, reject) => { complete = resolve; fail = reject; });
    // Events can fail before a queued job starts awaiting its result.
    void promise.catch(() => {});
    let stopped!: () => void;
    const terminal = new Promise<void>(resolve => { stopped = resolve; });
    const job: Job = { state, abort: new AbortController(), result: promise, complete, fail, terminal, stopped, submitted: false, effects: new Set() };
    this.jobs.set(job.state.turn_id, job); this.lanes[job.state.lane].push(job.state.turn_id);
    this.emit(job.state, 'turn.queued', {}); this.processLane(job.state.lane);
    return TurnStateSchema.parse(job.state);
  }
  private processLane(lane: TurnState['lane']): void {
    if (this.processors.has(lane)) return;
    const task = Promise.resolve().then(async () => {
      try {
        while (this.lanes[lane].length) {
          const id = this.lanes[lane].shift()!; const job = this.jobs.get(id);
          if (job) await this.execute(job);
        }
      } finally {
        // Release ownership in the same microtask that sees the queue empty.
        this.processors.delete(lane);
      }
    });
    this.processors.set(lane, task);
    // A persistence failure is fatal for this execution owner; never advance silently.
    void task.catch(() => { this.engineFailed = true; this.approvals.deny(); for (const job of this.jobs.values()) job.abort.abort(); });
  }
  private async ensureEngine(): Promise<void> {
    if (this.closed || this.engineFailed) throw new EngineError('引擎不可用，未自动重放');
    this.engineStarting ??= (async () => {
      this.engine = this.options.engine(); await this.engine.start();
      if (this.closed) throw new EngineError('服务已关闭');
      let ready!: () => void, fail!: (error: unknown) => void;
      const connection = new Promise<void>((resolve, reject) => { ready = resolve; fail = reject; });
      const timeout = setTimeout(() => fail(new EngineError('引擎事件流未就绪')), 15_000);
      this.consumer = this.consume(this.engine, ready, fail);
      try { await connection; } finally { clearTimeout(timeout); }
    })().catch(async error => {
      this.engineFailed = true; await this.engine?.close(); throw error;
    });
    await this.engineStarting;
  }
  private async consume(engine: Engine, ready: () => void, fail: (error: unknown) => void): Promise<void> {
    try { for await (const event of engine.events(ready)) this.consumeEvent(event); }
    catch { /* State and callers receive a sanitized terminal reason below. */ }
    finally {
      const error = new EngineError('引擎连接中断，未自动重试'); fail(error);
      this.engineFailed = true; this.approvals.deny();
      for (const job of this.jobs.values()) {
        if (job.state.workflow_version) continue;
        if (!this.closed) this.turns.blockEngine(job.state.engine_id);
        job.abort.abort(error); job.fail(error); job.stopped();
      }
    }
  }
  private consumeEvent(event: BridgeEvent): void {
    const job = this.jobs.get(event.turnId), state = job?.state;
    if (!job || !state || state.task_id !== event.taskId || state.engine_id !== event.sessionId) return;
    if (event.kind === 'usage' && event.data.usage && typeof event.data.usage === 'object') this.ledger.usage(state, event.sequence, event.data.usage);
    const terminal = ['turn.completed','turn.cancelled','turn.failed'].includes(event.kind);
    if (terminal) {
      job.stopped();
      job.complete(state.status === 'failed' ? 'failed' : state.status === 'cancelled' || event.kind === 'turn.cancelled' ? 'cancelled' : event.kind === 'turn.completed' ? 'completed' : 'failed'); return;
    }
    if (state.status !== 'running') return;
    if (event.kind === 'tool.request') {
      const effect = this.tool(job, event); job.effects.add(effect);
      void effect.finally(() => job.effects.delete(effect)).catch(() => {}); return;
    }
    if (event.kind === 'text.delta' || event.kind === 'text.final') {
      if (typeof event.data.text !== 'string') throw new EngineError('引擎文本事件无效');
      state.output_text = event.kind === 'text.delta' ? state.output_text + event.data.text : event.data.text;
      if (Buffer.byteLength(state.output_text) > 512000) throw new EngineError('回复超过限制');
      this.turns.save(state);
    }
    this.emit(state, event.kind, event.data);
  }
  private async tool(job: Job, event: BridgeEvent): Promise<void> {
    const callId = event.data.callId;
    if (typeof callId !== 'string') { await this.cancel(job.state.turn_id); return; }
    let result: Record<string, unknown>;
    try {
      const value = await job.tools!.execute(event.data);
      this.emit(job.state, 'tool.completed', { name: event.data.name ?? '', call_id: callId });
      result = { ok: true, value };
    } catch { result = { ok: false, error: '操作被拒绝、已取消或超出预算' }; }
    try { await this.engine?.call('tool.resolve', { callId, turnId: job.state.turn_id, ...result }); }
    catch { /* Loss of the stream separately terminates ownership; never replay a tool. */ }
  }
  private async execute(job: Job): Promise<void> {
    const state = job.state; let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      if (state.status === 'cancelled' || this.closed) { state.status = 'cancelled'; return; }
      this.options.beforeStart?.(state);
      if (state.workflow_version) {
        this.workflows.begin(state.workflow_version,state.turn_id);
        state.status = 'running'; this.turns.save(state);
        const settings = this.options.settings();
        const active = () => !this.closed && state.status === 'running' && !job.abort.signal.aborted && (!state.run_id || this.delegations.active(state.run_id));
        job.tools = new GovernedTools(state,settings,this.approvals,this.ledger.outcomes,job.abort.signal,active,this.options.applicationRoot,this.options.knowledge);
        const seconds = this.workflowExecution.startBudget(state.run_id,Math.min(settings.task_timeout,
          state.run_id ? this.delegations.get(state.delegation_id).spec.timeout_seconds : Infinity));
        timer = setTimeout(() => { state.error = '工作流超过设定时限'; job.abort.abort(new RpcFault('timeout')); this.approvals.deny(state.turn_id); },seconds * 1000);
        state.output_text = await this.workflowExecution.execute(state,job.tools,settings,job.abort.signal,active,prompt => this.analyze(prompt,job.abort.signal));
        job.abort.signal.throwIfAborted(); if (!active()) throw Error('执行权已失效');
        state.status = 'completed'; this.emit(state,'text.final',{ text: state.output_text }); return;
      }
      // Source freshness may retire engine mappings; resolve context before opening history.
      const context = await this.options.context?.(state) ?? '';
      job.abort.signal.throwIfAborted();
      this.turns.refreshEngine(state);
      await this.ensureEngine(); job.abort.signal.throwIfAborted();
      await this.engine!.call('session.open', { sessionId: state.engine_id, resume: this.turns.engineReady(state.engine_id) }, job.abort.signal);
      this.turns.markEngineReady(state.engine_id); job.abort.signal.throwIfAborted();
      state.status = 'running'; this.turns.save(state);
      const settings = this.options.settings();
      job.tools = new GovernedTools(state, settings, this.approvals, this.ledger.outcomes, job.abort.signal,
        () => !this.closed && state.status === 'running' && this.connected && !job.abort.signal.aborted,
        this.options.applicationRoot, this.options.knowledge);
      const image = state.image_id ? await this.options.images.get(state.image_id) : null;
      job.abort.signal.throwIfAborted();
      timer = setTimeout(() => {
        if (state.status !== 'running') return;
        state.error = '任务超过设定时限，已停止执行。';
        job.abort.abort(new RpcFault('timeout')); job.fail(new RpcFault('timeout')); this.approvals.deny(state.turn_id);
      }, settings.task_timeout * 1000);
      job.submitted = true;
      await this.engine!.call('turn.send', { sessionId: state.engine_id, taskId: state.task_id, turnId: state.turn_id,
        lane: state.lane, text: state.input_text, ...(context ? { context } : {}),
        image: image ? { image_id: image.image_id, media_type: image.media_type, width: image.width, height: image.height } : null }, job.abort.signal);
      state.status = await job.result;
      if (state.status === 'failed') state.error = '执行失败，请检查模型配置或服务连接。';
    } catch (error) {
      if (state.status !== 'cancelled') {
        state.status = 'failed';
        state.error ||= error instanceof EngineError ? error.message : '执行失败，请检查模型配置或服务连接。';
      }
      await this.stopTurn(job);
    } finally {
      clearTimeout(timer); job.abort.abort(); this.approvals.deny(state.turn_id);
      await Promise.allSettled(job.effects);
      this.workflowExecution.finishBudget(state.run_id);
      const settled = this.ledger.finish(state);
      if (state.workflow_version) this.workflows.observe(state.workflow_version,state.turn_id,
        state.status === 'cancelled' ? null : state.status === 'completed' && this.ledger.outcomes.get(state.turn_id).verdict === 'verified');
      this.jobs.delete(state.turn_id);
      for (const event of settled.events) this.options.publish(event);
      this.options.settled?.(state);
    }
  }
  private async stopTurn(job: Job): Promise<void> {
    if (!job.submitted || !this.connected) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      const result = await this.engine!.call('turn.cancel', { sessionId: job.state.engine_id, turnId: job.state.turn_id });
      if (result && typeof result === 'object' && 'cancelled' in result && result.cancelled === false) {
        job.stopped(); job.complete(job.state.status); return;
      }
      await Promise.race([job.terminal, new Promise<never>((_resolve, reject) => { timer = setTimeout(() => reject(Error('取消未确认')), 5000); })]);
    } catch { this.engineFailed = true; await this.engine?.close(); }
    finally { clearTimeout(timer); }
  }
  async cancel(id: string): Promise<TurnState> {
    const saved = this.turns.get(id), job = this.jobs.get(id); if (!job) return saved;
    job.state.status = 'cancelled'; job.state.error = ''; this.turns.save(job.state);
    this.approvals.deny(id); job.abort.abort(new RpcFault('cancelled'));
    if (!job.submitted) job.complete('cancelled');
    await this.stopTurn(job); return TurnStateSchema.parse(job.state);
  }
  close(): Promise<void> {
    this.closing ??= (async () => {
      this.closed = true; this.approvals.deny();
      for (const job of this.jobs.values()) { job.state.status = 'cancelled'; job.abort.abort(); job.complete('cancelled'); }
      await this.engine?.close(); await this.consumer; await Promise.allSettled(this.processors.values());
    })(); return this.closing;
  }
}
