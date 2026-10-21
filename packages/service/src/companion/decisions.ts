import { createHash } from 'node:crypto';
import { JevContextSchema, JevDecisionSchema, JevStatusSchema, type RuntimeSettings, type NotificationView } from '@lobuddy/contracts';
import { codepointSlice, SECRETS, SENSITIVE, sanitizeMemory } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { NotificationRepository } from '../storage/notifications.js';
import { JevRepository } from '../storage/jev.js';
import { decideJev, jevRequestBody, JevUnavailable, type JevClient } from '../engine/jev.js';
const digest = (body: Buffer) => createHash('sha256').update(body).digest('hex');
export class NotificationDecisions {
  readonly repo: JevRepository;
  private current?: { promise: Promise<void>; abort: AbortController };
  private closed = false;
  private generation = 0;
  constructor(readonly store: Store, readonly settings: () => RuntimeSettings,
    readonly notifications: NotificationRepository, readonly quiet: () => boolean, readonly goal: (id: string) => string,
    readonly credentials: () => { key: string; secrets: string[] }, readonly client: JevClient = decideJev,
    readonly clock = () => Date.now() / 1000) { this.repo = new JevRepository(store); }
  enabled(): boolean { return this.settings().jev_mode !== 'off' && Boolean(this.credentials().key); }
  allowed(notice: NotificationView): boolean {
    if (!this.enabled() || this.settings().jev_mode !== 'active' || notice.reason !== 'task_result') return true;
    const value = this.repo.get(notice.id); if (!value) return false;
    if (value.mode === 'shadow') return true;
    return value.status !== 'running' && (value.action === 'notify' || value.action === 'defer' && this.clock() >= value.not_before);
  }
  context(notice: NotificationView) {
    const goal = notice.delegation_id ? this.goal(notice.delegation_id) : '';
    const recent = this.notifications.list().filter(item => notice.delegation_id && item.delegation_id === notice.delegation_id &&
      item.id !== notice.id && ['delivered','read'].includes(item.status) && item.delivered_at !== null && this.clock() - item.delivered_at < 86400 && this.notifications.valid(item))
      .slice(0,3).map(item => codepointSlice(item.text,300));
    const text = [notice.text,goal,...recent].join('\n');
    if (sanitizeMemory(text) !== text.trim() || SECRETS.test(text) || SENSITIVE.test(text) ||
      this.credentials().secrets.some(key => key.length >= 6 && text.includes(key))) throw Error('私密内容不适合发送给 Jev');
    return JevContextSchema.parse({ notification: codepointSlice(notice.text,600),goal: codepointSlice(goal,600),recent_delivered: recent });
  }
  poll(): void {
    if (this.closed || !this.enabled() || this.quiet() || this.current) return;
    for (const notice of this.notifications.pending()) {
      if (notice.reason !== 'task_result' || !this.notifications.valid(notice) || this.repo.get(notice.id)) continue;
      const abort = new AbortController();
      const promise = Promise.resolve().then(() => this.decide(notice,abort.signal)).finally(() => { this.current = undefined; });
      this.current = { promise,abort }; void promise.catch(() => {}); break;
    }
  }
  private async decide(notice: NotificationView, signal: AbortSignal): Promise<void> {
    const settings = this.settings(), mode = settings.jev_mode; if (mode === 'off' || signal.aborted) return;
    const now = this.clock(), start = performance.now(), generation = this.generation;
    const value = JevDecisionSchema.parse({ reason: '正在判断；暂存收件箱',mode,status: 'running',created_at: now,not_before: now + 600 });
    let body: Buffer;
    try { body = jevRequestBody(this.context(notice),settings.jev_model); }
    catch {
      value.status = 'fallback'; value.reason = '内容不适合发送给 Jev，延后合并';
      this.repo.reserve(notice.id,'',value,0,0,0); value.reason = '内容不适合发送给 Jev，延后合并'; this.repo.finish(notice.id,value); return;
    }
    const hash = digest(body);
    if (!this.repo.reserve(notice.id,hash,value,body.length,settings.jev_daily_calls,settings.jev_daily_request_bytes)) return;
    try {
      const response = await this.client(body,this.credentials().key,signal); signal.throwIfAborted();
      const current = this.notifications.get(notice.id);
      if (this.closed || generation !== this.generation || this.quiet() || !current || ['cancelled','missed','read'].includes(current.status) ||
        !this.notifications.valid(current) || digest(jevRequestBody(this.context(current),this.settings().jev_model)) !== hash) {
        value.status = 'stale'; value.reason = '判断期间状态或来源已变化，延后合并';
      } else {
        value.model = response.model; value.answers = response.answers; value.status = 'decided';
        const { relevant,time_sensitive,duplicate } = response.answers, threshold = settings.jev_min_confidence;
        if (duplicate.choice === 'yes' && duplicate.confidence >= threshold || relevant.choice === 'no' && relevant.confidence >= threshold) {
          value.action = 'quiet'; value.reason = '内容重复或与当前委托无关，仅留收件箱';
        } else if ([relevant,time_sensitive,duplicate].some(answer => answer.confidence < threshold || answer.choice === 'unknown')) value.reason = '判断不确定，延后合并';
        else if (time_sensitive.choice === 'yes') { value.action = 'notify'; value.reason = '与委托相关且有时效性，允许提示'; }
        else value.reason = '没有明确时效性，延后十分钟合并';
      }
      value.input_tokens = response.usage.input_tokens; value.output_tokens = response.usage.output_tokens;
    } catch (error) {
      if (signal.aborted) { value.status = 'interrupted'; value.reason = '判断已取消，未自动重试'; }
      else if (error instanceof JevUnavailable) { value.status = 'fallback'; value.reason = `Jev 暂不可用（${error.message}），延后合并`; }
      else { value.status = 'stale'; value.reason = '来源已失效，延后合并'; }
    } finally { value.elapsed_ms = Math.round((performance.now() - start) * 100) / 100; this.repo.finish(notice.id,value); }
  }
  view() {
    const settings = this.settings(), used = this.repo.usage(this.clock());
    return JevStatusSchema.parse({ mode: settings.jev_mode,configured: Boolean(this.credentials().key),model: settings.jev_model,
      calls_today: used.calls,request_bytes_today: used.bytes,daily_calls: settings.jev_daily_calls,daily_request_bytes: settings.jev_daily_request_bytes,
      running: Boolean(this.current),recent: this.repo.recent() });
  }
  async stop(close = false): Promise<void> { this.closed = close; this.generation++; this.current?.abort.abort(); await this.current?.promise; }
}
