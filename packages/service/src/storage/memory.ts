import { MemoryItemSchema, ConversationSummarySchema, localTimestamp,
  type MemoryItem, type MemoryType, type MemoryStatus, type ConversationSummary } from '@lobuddy/contracts';
import { Store } from './database.js';
import { memoryQueryTerms } from '@lobuddy/domain';
const indexed = new WeakSet<Store>();

export class MemoryRepository {
  constructor(readonly store: Store) {
    // Historical stores can contain a stale external-content index. Repair once per owner.
    if (!indexed.has(store)) { this.rebuildIndex(); indexed.add(store); }
  }
  get(id: string): MemoryItem | undefined {
    const row = this.store.connection.prepare('SELECT * FROM memory_item WHERE id=?').get(id);
    return row ? MemoryItemSchema.parse(row) : undefined;
  }
  list(type?: MemoryType, status?: MemoryStatus, scope?: string, limit = 1000): MemoryItem[] {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 10000) throw new Error('记忆查询数量无效');
    return this.store.connection.prepare(`SELECT * FROM memory_item
      WHERE (? IS NULL OR memory_type=?) AND (? IS NULL OR status=?) AND (? IS NULL OR scope=?)
      ORDER BY updated_at DESC LIMIT ?`).all(type ?? null, type ?? null, status ?? null, status ?? null,
      scope ?? null, scope ?? null, limit).map(row => MemoryItemSchema.parse(row));
  }
  save(input: MemoryItem): MemoryItem {
    return this.saveBatch([input])[0]!;
  }
  saveBatch(inputs: MemoryItem[], record: () => void = () => {}): MemoryItem[] {
    const items = inputs.map(input => MemoryItemSchema.parse(input));
    this.store.transaction(() => {
      for (const m of items) {
      this.removeIndex(m.id);
      this.store.run(`INSERT INTO memory_item(id,memory_type,scope,title,content,source,source_session_id,
        source_message_id,confidence,importance,priority,status,expires_at,last_used_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        memory_type=excluded.memory_type,scope=excluded.scope,title=excluded.title,content=excluded.content,
        source=excluded.source,source_session_id=excluded.source_session_id,source_message_id=excluded.source_message_id,
        confidence=excluded.confidence,importance=excluded.importance,priority=excluded.priority,status=excluded.status,
        expires_at=excluded.expires_at,last_used_at=excluded.last_used_at,updated_at=excluded.updated_at`,
        m.id,m.memory_type,m.scope,m.title,m.content,m.source,m.source_session_id,m.source_message_id,
        m.confidence,m.importance,m.priority,m.status,m.expires_at,m.last_used_at,m.created_at,m.updated_at);
      this.store.run('INSERT INTO memory_item_fts(rowid,title,content) SELECT rowid,title,content FROM memory_item WHERE id=?',m.id);
      }
      record();
    });
    return items.map(item => this.get(item.id)!);
  }
  delete(id: string): boolean {
    return this.store.transaction(() => {
      this.removeIndex(id);
      const removed = this.store.run('DELETE FROM memory_item WHERE id=?', id).changes > 0;
      return removed;
    });
  }
  updateStatus(id: string, status: MemoryStatus): boolean {
    const item = this.get(id); if (!item) return false;
    this.save({ ...item, status, updated_at: localTimestamp() }); return true;
  }
  private rebuildIndex(): void {
    // Imported stores may have a stale external-content index; rebuild from the authority.
    this.store.run("INSERT INTO memory_item_fts(memory_item_fts) VALUES('rebuild')");
  }
  private removeIndex(id: string): void {
    this.store.run("INSERT INTO memory_item_fts(memory_item_fts,rowid,title,content) SELECT 'delete',rowid,title,content FROM memory_item WHERE id=?",id);
  }
  search(keyword: string, type?: MemoryType, limit = 10, fullText = false): MemoryItem[] {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1000) throw new Error('记忆查询数量无效');
    const rows = fullText ? this.store.connection.prepare(`SELECT m.* FROM memory_item m
      JOIN memory_item_fts f ON m.rowid=f.rowid WHERE memory_item_fts MATCH ? AND m.status='active'
      AND (? IS NULL OR m.memory_type=?) ORDER BY rank LIMIT ?`).all(keyword, type ?? null, type ?? null, limit) :
      this.store.connection.prepare(`SELECT * FROM memory_item WHERE status='active' AND (title LIKE ? OR content LIKE ?)
        AND (? IS NULL OR memory_type=?) ORDER BY importance DESC,updated_at DESC LIMIT ?`)
        .all(`%${keyword}%`, `%${keyword}%`, type ?? null, type ?? null, limit);
    return rows.map(row => MemoryItemSchema.parse(row));
  }
  recall(query: string, sessionId: string, limit = 5): MemoryItem[] {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1000) throw new Error('记忆查询数量无效');
    const terms = memoryQueryTerms(query); if (!terms.length) return [];
    const patterns = terms.flatMap(term => {
      const pattern = `%${term.replace(/[\\%_]/gu, '\\$&')}%`; return [pattern, pattern];
    });
    const score = terms.map(() => "CASE WHEN m.title LIKE ? ESCAPE '\\' THEN 3 WHEN m.content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END").join(' + ');
    const rows = this.store.connection.prepare(`SELECT * FROM (
      SELECT m.*,(${score}) AS recall_score FROM memory_item m
      WHERE m.memory_type='episodic_memory' AND m.status='active' AND m.scope IN ('global',?)
        AND (m.expires_at IS NULL OR julianday(m.expires_at)>julianday(?))
        AND NOT EXISTS (SELECT 1 FROM relationship_barrier b WHERE b.source_id=m.source_message_id)
      ) WHERE recall_score>0 ORDER BY recall_score DESC,importance DESC,updated_at DESC,id ASC LIMIT ?`)
      .all(...patterns, sessionId, new Date().toISOString(), limit);
    return rows.map(row => MemoryItemSchema.parse(row));
  }
  saveSummary(input: ConversationSummary): ConversationSummary {
    const s = ConversationSummarySchema.parse(input);
    this.store.run(`INSERT INTO conversation_summary VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
      session_id=excluded.session_id,summary_type=excluded.summary_type,content=excluded.content,
      from_message_id=excluded.from_message_id,to_message_id=excluded.to_message_id,token_estimate=excluded.token_estimate,
      updated_at=excluded.updated_at`, s.id,s.session_id,s.summary_type,s.content,s.from_message_id,s.to_message_id,
      s.token_estimate,s.created_at,s.updated_at);
    return s;
  }
  summaries(sessionId: string, limit = 10): ConversationSummary[] {
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1000) throw new Error('摘要查询数量无效');
    return this.store.connection.prepare('SELECT * FROM conversation_summary WHERE session_id=? ORDER BY created_at DESC LIMIT ?')
      .all(sessionId, limit).map(row => ConversationSummarySchema.parse(row));
  }
}
