import { ChatMessageSchema, ChatSessionSchema, localTimestamp, type ChatMessage, type ChatSession } from '@lobuddy/contracts';
import { Store } from './database.js';
const bounded = (value: number, max: number) => {
  if (!Number.isSafeInteger(value) || value < 1 || value > max) throw new Error('查询数量不符合限制'); return value;
};
export class ChatRepository {
  constructor(private readonly store: Store, private readonly invalidRecord: () => void = () => {}) {}
  getSession(id: string): ChatSession | undefined {
    const row = this.store.connection.prepare('SELECT * FROM chat_session WHERE id=?').get(id);
    return row ? ChatSessionSchema.parse({ ...row, messages: this.messages(id) }) : undefined;
  }
  sessions(limit = 20): ChatSession[] {
    return this.store.connection.prepare('SELECT * FROM chat_session ORDER BY updated_at DESC LIMIT ?').all(bounded(limit, 1000))
      .map(row => ChatSessionSchema.parse({ ...row, messages: [] }));
  }
  saveSession(value: ChatSession): void {
    const session = ChatSessionSchema.parse(value);
    this.store.run(`INSERT INTO chat_session(id,pet_id,title,created_at,updated_at) VALUES(?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET title=excluded.title,updated_at=excluded.updated_at`,
      session.id, session.pet_id, session.title, session.created_at, session.updated_at);
  }
  private decode(rows: unknown[]): ChatMessage[] {
    const messages: ChatMessage[] = [];
    for (const row of rows) {
      const value = ChatMessageSchema.safeParse(row);
      if (value.success) messages.push(value.data); else this.invalidRecord();
    }
    return messages;
  }
  messages(sessionId: string, limit = 1000): ChatMessage[] {
    return this.decode(this.store.connection.prepare('SELECT * FROM chat_message WHERE session_id=? ORDER BY created_at ASC LIMIT ?')
      .all(sessionId, bounded(limit, 1000)));
  }
  saveMessage(value: ChatMessage): void {
    const message = ChatMessageSchema.parse(value);
    this.store.transaction(() => {
      this.store.run(`INSERT INTO chat_message(id,session_id,role,content,image_path,created_at) VALUES(?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET session_id=excluded.session_id,role=excluded.role,content=excluded.content,image_path=excluded.image_path,created_at=excluded.created_at`,
        message.id, message.session_id, message.role, message.content, message.image_path, message.created_at);
      this.store.run('UPDATE chat_session SET updated_at=? WHERE id=?', localTimestamp(), message.session_id);
    });
  }
  search(query: string, sessionId?: string, limit = 10): ChatMessage[] {
    bounded(limit, 1000);
    const statement = sessionId ? this.store.connection.prepare('SELECT * FROM chat_message WHERE session_id=? AND content LIKE ? ORDER BY created_at DESC LIMIT ?') :
      this.store.connection.prepare('SELECT * FROM chat_message WHERE content LIKE ? ORDER BY created_at DESC LIMIT ?');
    return this.decode(sessionId ? statement.all(sessionId, `%${query}%`, limit) : statement.all(`%${query}%`, limit));
  }
  clear(id: string): void { this.store.run('DELETE FROM chat_message WHERE session_id=?', id); }
}
