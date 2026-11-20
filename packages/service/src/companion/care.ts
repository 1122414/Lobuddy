import { createHash } from 'node:crypto';
import { z } from 'zod';
import { CareItemSchema, CarePolicySchema, CareProposalSchema, CareUpdateSchema, CareSourceClockSchema, MemoryItemSchema,
  type CareItem, type CarePolicy, type CareProposal } from '@lobuddy/contracts';
import { careMessageTime, careNextAt, careWindow, REJECT_CONTEXT, SENSITIVE, SECRETS, sanitizeMemory } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { Preferences } from '../storage/preferences.js';
import { parseStoredJson } from '../storage/json.js';
import type { KnowledgeService } from '../knowledge/service.js';
import type { ProjectService } from '../knowledge/projects.js';

const hash = (value: string) => createHash('sha256').update(value).digest('hex');
const DAY = 86400;
const configReceipt = z.strictObject({id: z.string().min(1).max(128),fingerprint: z.string().regex(/^[a-f0-9]{64}$/u)});
export class CareService {
  private readonly preferences: Preferences;
  policy: CarePolicy;
  private reconciling = false;
  onChange = () => {};
  constructor(readonly store: Store,readonly knowledge: KnowledgeService,readonly projects: ProjectService,readonly clock = () => Date.now() / 1000) {
    this.preferences = new Preferences(store);
    const saved = this.preferences.get('care_policy');
    this.policy = CarePolicySchema.parse(saved === undefined ? { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone } : parseStoredJson(saved));
    if (saved === undefined) this.preferences.set('care_policy',JSON.stringify(this.policy));
    this.reconcile();
  }
  save(item: CareItem): void {
    const value = CareItemSchema.parse(item);
    this.store.run('INSERT INTO companion_care VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',value.id,JSON.stringify(value));
  }
  all(): CareItem[] {
    return this.store.connection.prepare('SELECT body FROM companion_care ORDER BY rowid DESC').all().map(row => CareItemSchema.parse(parseStoredJson(String(row.body))));
  }
  get(id: string): CareItem | undefined {
    const row = this.store.connection.prepare('SELECT body FROM companion_care WHERE id=?').get(id);
    return row ? CareItemSchema.parse(parseStoredJson(String(row.body))) : undefined;
  }
  fact(item: CareItem): string { return this.knowledge.repo.get(item.memory_id)?.content ?? ''; }
  sourceTime(sourceId: string) {
    const source = this.knowledge.relationship.sources([sourceId])[0]; if (!source) throw Error('近况来源已失效');
    const saved = this.preferences.get(`care_clock:${sourceId}`);
    return saved ? CareSourceClockSchema.parse(parseStoredJson(saved)) : {at:careMessageTime(source.created_at,this.policy.timezone),timezone:this.policy.timezone};
  }
  sourceTimeLabel(sourceId: string): string {
    const clock = this.sourceTime(sourceId);
    return new Date(clock.at * 1000).toLocaleString('zh-CN',{timeZone:clock.timezone,hour12:false}) + ` (${clock.timezone})`;
  }
  valid(item: CareItem): boolean {
    const source = this.knowledge.relationship.sources([item.source_id])[0],memory = this.knowledge.repo.get(item.memory_id);
    if (!source || source.role !== 'user' || !memory || memory.status !== 'active' || item.expires_at <= this.clock() ||
      hash(source.content + '\0' + memory.content) !== item.source_revision || !source.content.includes(memory.content) ||
      memory.expires_at !== null && Date.parse(memory.expires_at) / 1000 <= this.clock()) return false;
    if (item.project_id) { try { if (this.projects.repo.project(item.project_id).status !== 'active') return false; } catch { return false; } }
    return this.projects.repo.selection(item.session_id).project_id === item.project_id;
  }
  reconcile(): void {
    if (this.reconciling) return;
    this.reconciling = true;
    try {
      for (const item of this.all()) {
        if (item.status === 'invalid') continue;
        if (!this.valid(item)) {
          item.status = 'invalid'; item.title = '来源已失效'; item.revision++; item.updated_at = this.clock(); this.save(item);
          this.knowledge.gateway.delete(item.memory_id); this.onChange();
        } else if (item.status === 'preparing') { item.status = 'active'; this.save(item); }
      }
    } finally { this.reconciling = false; }
  }
  configure(input: CarePolicy, requestId = ''): CarePolicy {
    const value = CarePolicySchema.parse(input), fingerprint = hash(JSON.stringify(value));
    const last = this.preferences.get('care_config_request');
    if (requestId && last) {
      const previous = configReceipt.parse(parseStoredJson(last));
      if (previous.id === requestId) { if (previous.fingerprint !== fingerprint) throw Error('重试内容与原配置不一致'); return this.policy; }
    }
    if (value.revision !== this.policy.revision) throw Error('关心设置已更新，请刷新后重试');
    const next = { ...value,revision: value.revision + 1 };
    this.store.transaction(() => {
      this.preferences.set('care_policy',JSON.stringify(next));
      if (requestId) this.preferences.set('care_config_request',JSON.stringify({ id: requestId,fingerprint }));
    });
    this.policy = next; this.onChange(); return this.policy;
  }
  view() {
    this.reconcile();
    return { policy: this.policy,items: this.all().filter(item => item.status !== 'invalid').slice(0,100).map(item => ({ ...item,fact: this.fact(item) })) };
  }
  admit(input: CareProposal, sessionId: string): CareItem | undefined {
    if (!this.policy.enabled || !this.knowledge.relationship.enabled) return;
    const proposal = CareProposalSchema.parse(input), source = this.knowledge.relationship.sources([proposal.source_id])[0];
    if (!source || source.role !== 'user' || source.session_id !== sessionId || !source.content.includes(proposal.quote) ||
      !proposal.quote.includes(proposal.subject) || sanitizeMemory(source.content) !== source.content ||
      REJECT_CONTEXT.test(source.content) || SENSITIVE.test(source.content) || SECRETS.test(source.content) || /你(?:刚才)?说|助手说|模型说|AI说/u.test(source.content) ||
      /(?:朋友|同事|他|她|别人|你)(?:明天|今天|后天|最近|想|要|准备|打算|计划)/u.test(source.content) ||
      !/(?:我(?:明天|今天|后天|这周|下周|本周|最近|准备|打算|要|在|想|的|会|已经|刚|周|计划|还|正|决定)|^(?:今天|明天|后天|本周|这周|下周).*(?:面试|考试|准备|打算|计划))/u.test(source.content) ||
      !/面试|考试|创作|画|写|制作|计划|准备|打算|项目|练|学习|作品/u.test(proposal.quote) || /提醒我|帮我安排/u.test(source.content)) return;
    const id = hash(`care:${source.id}:${proposal.subject}`), previous = this.all().find(item => item.source_id === source.id) ?? this.get(id);
    if (previous) return previous.status === 'invalid' ? undefined : previous;
    if (this.all().filter(item => ['active','deferred','preparing'].includes(item.status)).length >= 50) return;
    const sourceClock = this.sourceTime(source.id);
    const now = this.clock(), at = sourceClock.at;
    if (at > now + 60 || at < now - 14 * DAY) return;
    const next = careNextAt(source.content,at,sourceClock.timezone), expires = Math.max(at + 14 * DAY,next + 7 * DAY);
    const item = CareItemSchema.parse({ id,memory_id: id,source_id: source.id,source_revision: hash(source.content + '\0' + proposal.quote),
      session_id: sessionId,project_id: this.projects.repo.selection(sessionId).project_id,title: proposal.subject,revision: 1,status: 'preparing',
      next_at: next,expires_at: expires,unanswered: 0,last_presented_at: 0,last_response_id: '',created_at: now,updated_at: now });
    this.save(item);
    this.knowledge.gateway.saveAdmitted(MemoryItemSchema.parse({ id,memory_type: 'episodic_memory',title: `近况 · ${proposal.subject}`,
      content: proposal.quote,scope: sessionId,source: 'relationship',source_session_id: sessionId,source_message_id: source.id,
      confidence: 1,priority: 60,created_at:new Date(at * 1000).toISOString(),expires_at: new Date(expires * 1000).toISOString() }));
    item.status = 'active'; this.save(item); return item;
  }
  update(input: unknown, requestId = ''): CareItem {
    this.reconcile(); const value = CareUpdateSchema.parse(input), item = this.get(value.id);
    if (!item || item.status === 'invalid') throw Error('这件近况的来源已失效');
    const fingerprint = hash(JSON.stringify(value));
    const previous = requestId ? this.store.connection.prepare('SELECT * FROM companion_care_request WHERE id=?').get(requestId) : undefined;
    if (previous) { if (previous.fingerprint !== fingerprint || previous.care_id !== item.id) throw Error('重试内容与原操作不一致'); return item; }
    if (value.revision !== item.revision) throw Error('近况已更新，请刷新后重试');
    const now = this.clock();
    if (value.action === 'defer') {
      const next = value.until ?? now + 48 * 3600;
      if (next < now + 48 * 3600 || next > item.expires_at) throw Error('延期须至少48小时，且不能超过来源有效期');
      item.next_at = next; item.status = 'deferred';
    } else if (value.action === 'resume') {
      if (now + 48 * 3600 >= item.expires_at) throw Error('原近况即将到期，请重新分享有效近况');
      item.status = 'active'; item.next_at = now + 48 * 3600; item.unanswered = 0;
    }
    else item.status = value.action === 'pause' ? 'paused' : 'closed';
    item.revision++; item.updated_at = now;
    this.store.transaction(() => {
      this.save(item);
      if (value.action === 'resume') this.store.run('UPDATE companion_topic SET blocked=0,cooldown_until=0 WHERE id=?',`care:${item.id}`);
      if (requestId) this.store.run('INSERT INTO companion_care_request VALUES(?,?,?)',requestId,fingerprint,item.id);
    });
    this.onChange(); return item;
  }
  inWindow(): boolean { return this.policy.enabled && careWindow(this.clock(),this.policy.timezone,this.policy.start_hour,this.policy.end_hour); }
  due(): CareItem[] {
    this.reconcile(); if (!this.inWindow() || !this.knowledge.relationship.enabled) return [];
    return this.all().filter(item => ['active','deferred'].includes(item.status) && item.next_at <= this.clock()).sort((a,b) => a.next_at - b.next_at);
  }
  material(id: string) {
    if (!this.policy.enabled || !this.knowledge.relationship.enabled) return;
    const item = this.get(id);
    if (!item || !['active','deferred'].includes(item.status) || !this.valid(item)) return;
    return { text: this.fact(item),revision: item.source_revision,topic: `care:${id}`,project_id: item.project_id,session_id: item.session_id,source_time:this.sourceTimeLabel(item.source_id) };
  }
  presented(id: string): void {
    const item = this.get(id);
    if (!item || !this.material(id) || item.unanswered >= 2) throw Error('这件近况暂不适合再问');
    item.unanswered++; item.last_presented_at = this.clock(); item.next_at = this.clock() + 48 * 3600;
    item.revision++; item.updated_at = this.clock(); this.save(item);
  }
  unanswered(id: string): void {
    const item = this.get(id); if (!item || !['active','deferred'].includes(item.status) || item.unanswered < 2) return;
    item.status = 'paused'; item.revision++; item.updated_at = this.clock(); this.save(item); this.onChange();
  }
  respond(id: string, sourceId: string): boolean {
    const item = this.get(id),source = this.knowledge.relationship.sources([sourceId])[0];
    if (!item || !this.material(id) || !source || source.role !== 'user' || source.session_id !== item.session_id ||
      source.id === item.last_response_id || REJECT_CONTEXT.test(source.content)) return false;
    let value = source.content.trim().replace(/[。！!]+$/u,'');
    const known = [...new Set([item.title,...this.fact(item).match(/面试|考试|作品|项目/gu) ?? []])].sort((a,b)=>b.length-a.length);
    for (const subject of known) {
      if (value.startsWith(subject)) { value = value.slice(subject.length); break; }
      if (value.endsWith(subject) && /^(?:暂时不聊|先不聊|别再问|不要再问)/u.test(value)) { value = value.slice(0,-subject.length); break; }
    }
    const now = this.clock();
    let next = item.next_at, status = item.status;
    if (/^(?:这件事)?(?:已经)?(?:结束了|完成了|做完了)$/u.test(value)) status = 'closed';
    else if (/^(?:这件事)?(?:别再问(?:了)?|不要再问(?:了)?|以后别提(?:了)?)$/u.test(value)) status = 'paused';
    else if (/^(?:这件事)?(?:暂时不聊|稍后再聊|先不聊)(?:了)?$/u.test(value)) { status = 'deferred'; next = now + 48 * 3600; }
    else if (/^(?:还)?(?:没有|没)(?:新的?)?(?:进展|变化)(?:呢)?$/u.test(value)) { status = 'deferred'; next = now + 7 * 86400; }
    else if (/再(?:聊|问|提)|问我|找我聊/u.test(value)) {
      const clock = this.sourceTime(source.id);
      status = 'deferred'; next = careNextAt(value,clock.at,clock.timezone);
    }
    else if (/^(?:还没开始|还没做|尚未开始|还在准备)(?:呢)?$/u.test(value)) { status = 'active'; next = now + 48 * 3600; }
    else return false;
    item.status = status; item.next_at = next; item.unanswered = 0; item.last_response_id = sourceId;
    item.revision++; item.updated_at = now; this.save(item); this.onChange(); return true;
  }
}
