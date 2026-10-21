import { MemoryItemSchema, ConversationSummarySchema, localTimestamp, type MemoryItem, type ConversationSummary } from '@lobuddy/contracts';
import { sanitizeMemory, stableIdentity } from '@lobuddy/domain';
import { MemoryRepository } from '../storage/memory.js';
import { randomUUID } from 'node:crypto';

export class MemoryWriteGateway {
  constructor(readonly repository: MemoryRepository, private readonly refresh: () => void = () => {}) {}
  private save(input: MemoryItem): MemoryItem {
    const value = this.repository.save(MemoryItemSchema.parse({ ...input, title: sanitizeMemory(input.title),
      content: sanitizeMemory(input.content), updated_at: localTimestamp() }));
    this.refresh(); return value;
  }
  saveManual(input: MemoryItem): MemoryItem {
    const content = sanitizeMemory(input.content);
    if (!content || [...content].length > 2000) throw new Error('记忆内容长度无效');
    return this.save({ ...input, content, source: 'manual', confidence: 1, priority: 100 });
  }
  saveRelationship(input: MemoryItem): MemoryItem {
    if (!input.content || [...input.content].length > 1000 || sanitizeMemory(input.content) !== input.content) {
      throw new Error('相处记忆内容无效');
    }
    return this.save({ ...input, source: 'relationship' });
  }
  delete(id: string): boolean { const result = this.repository.delete(id); this.refresh(); return result; }
  saveSummary(input: ConversationSummary): ConversationSummary {
    return this.repository.saveSummary(ConversationSummarySchema.parse({ ...input, content: sanitizeMemory(input.content) }));
  }
  saveAdmitted(input: MemoryItem): MemoryItem { return this.save(input); }
  refreshProjection(): void { this.refresh(); }
  identity(name: string, sessionId: string, sourceId: string): MemoryItem {
    const content = sanitizeMemory(`My name is ${name}.`);
    const records = this.repository.list('system_profile', 'active', undefined, 100);
    const existing = records.find(item => item.content.includes(content) || content.includes(item.content));
    if (existing) return this.save({ ...existing, source: 'strong_signal', source_session_id: sessionId,
      source_message_id: sourceId, confidence: Math.max(existing.confidence, 0.95), importance: Math.max(existing.importance, 0.9) });
    for (const item of records) if (item.title === 'Identity' && item.source === 'strong_signal') this.repository.updateStatus(item.id, 'deprecated');
    return this.save(MemoryItemSchema.parse({ id: randomUUID(), memory_type: 'system_profile', title: 'Identity', content,
      source: 'strong_signal', source_session_id: sessionId, source_message_id: sourceId, confidence: 0.95, importance: 0.9, priority: 96 }));
  }
  recordExperience(eventId: string, title: string, content: string, sessionId?: string): MemoryItem {
    const id = stableIdentity(`experience:${eventId}`), existing = this.repository.get(id);
    if (existing) return existing;
    const expiry = new Date(); expiry.setDate(expiry.getDate() + 90);
    return this.save(MemoryItemSchema.parse({ id, memory_type: 'episodic_memory', title, content,
      source: 'app_event', source_session_id: sessionId ?? null, source_message_id: eventId,
      confidence: 1, importance: 0.4, priority: 40, expires_at: expiry.toISOString() }));
  }
}
