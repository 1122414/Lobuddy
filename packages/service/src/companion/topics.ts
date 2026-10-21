import { createHash } from 'node:crypto';
import { type MemoryItem, type TopicChoice, type TopicView, type CompanionOverview } from '@lobuddy/contracts';
import { REJECT_CONTEXT, SENSITIVE, SECRETS, sanitizeMemory } from '@lobuddy/domain';
import { MemoryRepository } from '../storage/memory.js';
import { Store } from '../storage/database.js';
const hash = (text: string) => createHash('sha256').update(text).digest('hex');
export const memoryExpired = (item: MemoryItem, now = Date.now() / 1000) => item.expires_at !== null && new Date(item.expires_at).getTime() <= now * 1000;
export class TopicService {
  externalValid?: (id: string) => boolean;
  externalLabel?: (id: string) => string;
  readonly memory: MemoryRepository;
  constructor(readonly store: Store, readonly clock = () => Date.now() / 1000) { this.memory = new MemoryRepository(store); }
  identity(item: MemoryItem): string { return hash(`${item.memory_type}:${item.title || item.id}`); }
  revision(item: MemoryItem): string { return hash(`${item.id}:${item.content}`); }
  private records(): MemoryItem[] {
    return ['episodic_memory', 'user_profile'].flatMap(type => this.memory.list(type as 'user_profile' | 'episodic_memory', 'active')).filter(item => this.sourceValid(item));
  }
  sourceValid(item: MemoryItem): boolean {
    return !item.source_message_id || !this.store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get(item.source_message_id);
  }
  allowed(topic: string, revision: string): boolean {
    const row = this.store.connection.prepare('SELECT * FROM companion_topic WHERE id=?').get(topic);
    return !row || !(row.blocked || Number(row.cooldown_until) > this.clock() ||
      (row.revision === revision && this.clock() - Number(row.shown_at) < 7 * 86400));
  }
  blockMatching(subject: string): void {
    for (const item of this.records()) if (item.scope === 'global' && item.content.includes(subject)) {
      const topic = { topic_id: this.identity(item), memory_id: item.id, revision: this.revision(item), text: '' };
      this.shown(topic); this.feedback(topic.topic_id, 'never');
    }
  }
  choose(): TopicChoice | undefined {
    const items = this.records().sort((a, b) => a.updated_at > b.updated_at ? -1 : a.updated_at < b.updated_at ? 1 : 0);
    for (const item of items) {
      if (item.scope !== 'global' || memoryExpired(item, this.clock()) || [...item.content].length > 150 ||
        SENSITIVE.test(item.content) || SECRETS.test(item.content) || sanitizeMemory(item.content) !== item.content) continue;
      if (item.memory_type === 'user_profile' && (REJECT_CONTEXT.test(item.content) || !['喜欢', '爱好', '偏好'].some(word => item.content.includes(word)))) continue;
      if (item.memory_type === 'episodic_memory' && !['app_event', 'relationship', 'manual'].includes(item.source)) continue;
      const id = this.identity(item), revision = this.revision(item); if (!this.allowed(id, revision)) continue;
      return { topic_id: id, memory_id: item.id, revision,
        text: `${item.memory_type === 'episodic_memory' ? '我们之前留下了一段记录' : '你之前提到'}：「${item.content}」想接着聊聊吗？` };
    }
    return;
  }
  shown(topic: TopicChoice): void {
    this.store.run(`INSERT INTO companion_topic(id,memory_id,revision,shown_at) VALUES(?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET memory_id=excluded.memory_id,revision=excluded.revision,shown_at=excluded.shown_at`,
      topic.topic_id,topic.memory_id,topic.revision,this.clock());
  }
  valid(id: string): boolean {
    if (this.externalValid) return this.externalValid(id);
    const item = this.memory.get(id); if (!item || !this.sourceValid(item) || item.status !== 'active' || memoryExpired(item, this.clock())) return false;
    const row = this.store.connection.prepare('SELECT revision,blocked FROM companion_topic WHERE id=?').get(this.identity(item));
    return Boolean(row && !row.blocked && row.revision === this.revision(item));
  }
  feedback(id: string, action: string): void {
    if (action === 'never') this.store.run('UPDATE companion_topic SET blocked=1 WHERE id=?', id);
    else if (['later','ignored'].includes(action)) this.store.run('UPDATE companion_topic SET cooldown_until=? WHERE id=?', this.clock() + 86400,id);
    else if (action === 'unblock') this.store.run('UPDATE companion_topic SET blocked=0,cooldown_until=0 WHERE id=?', id);
  }
  list(): TopicView[] {
    return this.store.connection.prepare('SELECT * FROM companion_topic ORDER BY shown_at DESC LIMIT 100').all().map(row => ({
      topic_id: String(row.id), memory_id: String(row.memory_id), blocked: Boolean(row.blocked), cooldown_until: Number(row.cooldown_until),
      label: this.memory.get(String(row.memory_id))?.content ?? this.externalLabel?.(String(row.memory_id)) ?? '来源记忆已删除',
    }));
  }
  overview(): CompanionOverview {
    const records = (type: 'user_profile' | 'episodic_memory') => this.memory.list(type, 'active', undefined, 100)
      .filter(item => this.sourceValid(item) && !memoryExpired(item, this.clock()) && (type === 'episodic_memory' || item.title.startsWith('相处 ·')))
      .map(item => ({ id: item.id, content: item.content, source: item.source, at: item.created_at }));
    const verified = this.store.connection.prepare("SELECT name FROM workflow_version WHERE status='stable' AND observed>=5").all();
    return { experiences: records('episodic_memory'), preferences: records('user_profile'),
      verified_skills: verified.map(row => row.name === 'assistant-context' ? '上下文无损压缩（仅字段完整性与格式开销验证）' : String(row.name)),
      available: ['文字交流', '前台对话与后台任务', '专注计时', '记忆与技能管理'] };
  }
}
