import { LearningPolicySchema, JsonRecordSchema, type LearningPolicy, type LearningView, type LearningConsumer } from '@lobuddy/contracts';
import { LearningRepository, type Reservation, type LearningClaim } from '../storage/learning.js';
import { Preferences } from '../storage/preferences.js';
import { Store } from '../storage/database.js';
import { WorkflowProposalError } from './evolution.js';
export type LearningHandler = Reservation & { run: (source: string, signal: AbortSignal) => Promise<unknown> };
export class LearningService {
  readonly repo: LearningRepository;
  private readonly preferences: Preferences;
  policy: LearningPolicy;
  readonly handlers = new Map<string, LearningHandler>();
  consumers: () => LearningConsumer[] = () => [];
  private lastActivity: number;
  private worker?: ReturnType<typeof setInterval>;
  private current?: { promise: Promise<void>; abort: AbortController; remaining: Reservation; analysisInvoked: boolean };
  private closed = false;
  constructor(store: Store, private readonly busy: () => boolean, readonly clock = () => Date.now() / 1000) {
    this.repo = new LearningRepository(store); this.preferences = new Preferences(store);
    this.policy = LearningPolicySchema.parse(this.preferences.json('learning_policy'));
    this.lastActivity = clock(); this.repo.recover(clock());
  }
  start(): void {
    if (this.closed || this.worker || !this.policy.enabled) return;
    this.worker = setInterval(() => {
      try { this.enqueue('maintenance', this.repo.day(this.clock())); this.tick(); }
      catch { this.stopTimer(); } // Persistence failure stops this execution owner.
    }, 1000); this.worker.unref();
  }
  private stopTimer(): void { if (this.worker) clearInterval(this.worker); this.worker = undefined; }
  enqueue(kind: string, source: string): void { if (!this.closed && this.policy.enabled) this.repo.enqueue(kind,source,this.clock()); }
  async configure(input: LearningPolicy): Promise<LearningView> {
    this.policy = LearningPolicySchema.parse(input); this.preferences.set('learning_policy', JSON.stringify(this.policy));
    await this.activity(); if (!this.policy.enabled) this.stopTimer(); this.start(); return this.view();
  }
  async activity(): Promise<void> {
    this.lastActivity = this.clock(); this.current?.abort.abort(); await this.current?.promise;
  }
  tick(): void {
    if (this.closed || !this.policy.enabled) return;
    if (this.busy()) { this.lastActivity = this.clock(); return; }
    if (this.current || this.clock() - this.lastActivity < this.policy.idle_seconds) return;
    for (const [kind, handler] of this.handlers) {
      const claimed = this.repo.claim(kind,this.clock(),this.policy,handler); if (!claimed) continue;
      const abort = new AbortController();
      const promise = Promise.resolve().then(() => this.run(claimed,handler,abort.signal)).finally(() => { this.current = undefined; });
      this.current = { abort, promise, remaining: { ...claimed.reservation },analysisInvoked: false };
      void promise.catch(() => this.stopTimer()); return;
    }
  }
  async analyze(prompt: string, signal: AbortSignal, call: (prompt: string, signal: AbortSignal, maxTokens: 1024 | 2048) => Promise<string>,
    maxTokens: 1024 | 2048 = 1024): Promise<string> {
    const current = this.current; if (current) current.analysisInvoked = true; signal.throwIfAborted();
    // Byte count is a conservative token bound; reserve once before leaving this process.
    const size = Buffer.byteLength(prompt);
    if (!current || current.abort.signal.aborted || current.remaining.calls < 1 ||
      size > current.remaining.input_tokens || maxTokens > current.remaining.output_tokens) throw Error('后台调用没有可用预留额度');
    current.remaining.calls--; current.remaining.input_tokens -= size; current.remaining.output_tokens -= maxTokens;
    const result = await call(prompt,AbortSignal.any([signal,current.abort.signal]),maxTokens);
    signal.throwIfAborted(); current.abort.signal.throwIfAborted(); return result;
  }
  private async run(claimed: LearningClaim, handler: LearningHandler, owner: AbortSignal): Promise<void> {
    const timeout = new AbortController(), timer = setTimeout(() => timeout.abort(),60000);
    const signal = AbortSignal.any([owner, timeout.signal]),current = this.current;
    try {
      const result = await handler.run(claimed.source,signal); signal.throwIfAborted();
      const unused = current?.abort.signal === owner && !current.analysisInvoked;
      this.repo.finish(claimed,'completed',this.clock(),JSON.stringify(JsonRecordSchema.parse(result)),'',unused);
    } catch (error) {
      this.repo.finish(claimed,owner.aborted ? 'interrupted' : 'failed',this.clock(),'{}',owner.aborted ?
        '前台活动或服务退出，已中断' : error instanceof WorkflowProposalError ? `工作流提议未完成（${error.code}）；原稳定版本保持生效` : '处理未完成，最多尝试三次；请检查服务状态');
    } finally { clearTimeout(timer); }
  }
  view(): LearningView {
    const used = this.repo.usage(this.clock());
    return { policy: this.policy, usage: used, jobs: this.repo.jobs(), consumers: this.consumers(),
      state: this.closed ? 'closed' : !this.policy.enabled ? 'disabled' : this.current ? 'running' :
        this.busy() || this.clock() - this.lastActivity < this.policy.idle_seconds ? 'waiting' :
          used.calls >= this.policy.daily_calls || used.input_tokens >= this.policy.daily_input_tokens || used.output_tokens >= this.policy.daily_output_tokens ? 'budget_exhausted' : 'idle' };
  }
  async close(): Promise<void> { this.closed = true; this.stopTimer(); await this.activity(); }
}
