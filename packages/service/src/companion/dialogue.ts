import { createHash } from 'node:crypto';
import { Temporal } from '@js-temporal/polyfill';
import { DialogueStateSchema, QuietBoundarySchema,
  type TurnState, type QuietBoundary, type TopicChoice } from '@lobuddy/contracts';
import { dialogueIntent } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { parseStoredJson } from '../storage/json.js';
import { RelationshipService } from '../knowledge/relationship.js';
import { ProjectService } from '../knowledge/projects.js';
import { Companionship } from './policy.js';
import { memoryExpired } from './topics.js';
import { InvitationPlanner } from './invitations.js';
type Learning = {
  enabled: () => boolean; quiet: () => boolean; canReserve: (input: number, output: number, calls?: number) => boolean;
  enqueue: (kind: string, source: string) => void; analyze: (prompt: string) => Promise<string>;
};
const hash = (value: string) => createHash('sha256').update(value).digest('hex');
export class CompanionDialogue {
  externalMaterial?: (id: string) => { text: string; revision: string; topic: string; project_id: string; session_id?: string; source_time?: string } | undefined;
  readonly invitations: InvitationPlanner;
  constructor(readonly store: Store, readonly companion: Companionship, readonly relationship: RelationshipService,
    readonly projects: ProjectService, readonly learning: Learning, readonly clock = () => Date.now() / 1000) {
    this.invitations = new InvitationPlanner(this);
    companion.deferUntil = () => this.invitations.deferUntil();
    companion.topics.externalValid = id => this.valid(id); companion.topics.externalLabel = id => this.label(id);
    companion.selectTopic = () => this.choose(); companion.waitPreparation = () => this.waiting();
  }
  boundaries(): QuietBoundary[] {
    return this.store.connection.prepare('SELECT body FROM dialogue_boundary').all().map(row => {
      const value = QuietBoundarySchema.parse(parseStoredJson(String(row.body)));
      if (value.expires_at !== null && value.expires_at <= this.clock()) value.active = false;
      return value;
    });
  }
  blocked(text: string, project = false): boolean {
    return this.boundaries().some(b => b.active && (text.includes(b.subject) || b.subject === '工作' && project));
  }
  clear(): void {
    this.invitations.invalidate(); this.store.run('DELETE FROM dialogue_invitation'); this.companion.state.notice = null; this.companion.save();
  }
  release(id: string): void {
    const value = this.boundaries().find(item => item.id === id); if (!value) throw Error('交流边界不存在');
    this.store.run('INSERT OR REPLACE INTO dialogue_boundary VALUES(?,?)', id,JSON.stringify({ ...value, active: false }));
    this.clear();
  }
  respond(state: TurnState): void {
    const intent = dialogueIntent(state.input_text); if (!intent) return;
    let mode = intent.mode ?? (state.lane === 'background' ? 'executing' : this.state(state.session_id)?.mode ?? 'discussing');
    let reason = mode === 'listening' ? '先自然接话，不说教、不安排任务、不连续追问' : '当前会话，随下一次明确表达更新';
    for (const { subject, temporary } of intent.boundaries) {
      const until = temporary ? Temporal.Instant.fromEpochMilliseconds(Math.trunc(this.clock() * 1000))
        .toZonedDateTimeISO('Asia/Shanghai').add({ days: 1 }).startOfDay().epochMilliseconds / 1000 : null;
      const value = QuietBoundarySchema.parse({ id: hash(subject), subject, expires_at: until, reason: '用户明确的交流边界；不取消已授权任务' });
      this.store.run('INSERT OR REPLACE INTO dialogue_boundary VALUES(?,?)', value.id,JSON.stringify(value));
      mode = 'quiet'; reason = '尊重当前话题边界，不自行重排提醒或取消任务'; this.clear();
    }
    const value = DialogueStateSchema.parse({ session_id: state.session_id, mode, expires_at: this.clock() + 3600, reason });
    this.store.run('INSERT OR REPLACE INTO dialogue_state VALUES(?,?)', state.session_id,JSON.stringify(value));
  }
  state(sessionId: string) {
    const row = this.store.connection.prepare('SELECT body FROM dialogue_state WHERE session_id=?').get(sessionId);
    const value = row ? DialogueStateSchema.parse(parseStoredJson(String(row.body))) : undefined;
    return value && value.expires_at > this.clock() ? value : undefined;
  }
  context(state: TurnState): string {
    const current = this.state(state.session_id);
    return '\n当前交流状态（临时，不是用户性格）：' + (current ? JSON.stringify(current) : '自然接话') +
      '\n当前不主动提及的话题：' + JSON.stringify(this.boundaries().filter(b => b.active).map(b => b.subject)) +
      '。先倾听时允许短回应或沉默，不连续追问；不要把每句话变成建议。\n';
  }
  material(id: string): { text: string; revision: string; topic: string; project_id: string; session_id?: string; source_time?: string } | undefined {
    if (id.startsWith('care:') || id.startsWith('news:')) return this.externalMaterial?.(id);
    if (id.startsWith('project:')) {
      let value; try { value = this.projects.fresh(this.projects.repo.source(id.slice(8))); } catch { return; }
      if (value.status !== 'active' || value.sensitive || !['recent','pending','shared','decision'].includes(value.category) ||
        value.session_id || (value.project_id && this.projects.repo.project(value.project_id).status !== 'active')) return;
      return { text: value.text, revision: String(value.revision), topic: `project:${value.id}`, project_id: value.project_id };
    }
    const memory = this.companion.topics.memory.get(id);
    if (!memory || !this.companion.topics.sourceValid(memory) || memoryExpired(memory, this.clock()) || memory.status !== 'active' || memory.scope !== 'global') return;
    return { text: memory.content, revision: this.companion.topics.revision(memory), topic: this.companion.topics.identity(memory), project_id: '' };
  }
  source(id: string) {
    const source = this.material(id);
    return source && !this.blocked(source.text, Boolean(source.project_id)) ? source : undefined;
  }
  label(id: string): string { return this.source(id)?.text ?? '来源已失效或不可主动提及'; }
  valid(id: string): boolean {
    const source = this.source(id); if (!source) return false;
    const row = this.store.connection.prepare('SELECT revision,blocked FROM companion_topic WHERE id=?').get(source.topic);
    return Boolean(row && !row.blocked && row.revision === source.revision);
  }
  enqueue(): void { this.invitations.enqueue(); }
  prepare(id: string): Promise<Record<string, string | boolean>> { return this.invitations.prepare(id); }
  waiting(): boolean { return this.invitations.waiting(); }
  choose(): TopicChoice | undefined { return this.invitations.choose(); }
}
