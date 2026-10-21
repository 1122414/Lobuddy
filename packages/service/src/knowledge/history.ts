import { SessionSearchResponseSchema, trimUserText, type SessionSearchResponse } from '@lobuddy/contracts';
import { sanitizeMemory, codepointSlice } from '@lobuddy/domain';
import { ChatRepository } from '../storage/chat.js';
import { Store } from '../storage/database.js';
type SearchSettings = { memory_session_search_default_scope: string; memory_session_search_max_result_chars: number;
  memory_session_search_total_budget_chars: number };
export class HistorySearch {
  constructor(private readonly store: Store, private readonly settings: () => SearchSettings) {}
  search(query: string, sessionId: string, scope = 'current_session', limit = 5): SessionSearchResponse {
    query = trimUserText(query); const settings = this.settings();
    const result = SessionSearchResponseSchema.parse({ query, scope });
    if (!query) { result.note = 'Empty query rejected.'; return result; }
    if (scope !== 'all_sessions' || settings.memory_session_search_default_scope !== 'all_sessions') scope = 'current_session';
    result.scope = scope; limit = Math.min(Math.max(Math.trunc(limit), 1), 10);
    const messages = new ChatRepository(this.store).search(query, scope === 'current_session' ? sessionId : undefined, limit * 2)
      .filter(m => !this.store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get(m.id));
    if (!messages.length) { result.note = 'No results found.'; return result; }
    let used = 0;
    for (const m of messages.slice(0, limit)) {
      let content = sanitizeMemory(m.content); if (!content) continue;
      if ([...content].length > settings.memory_session_search_max_result_chars) content = codepointSlice(content, settings.memory_session_search_max_result_chars) + '...';
      if (used + [...content].length > settings.memory_session_search_total_budget_chars) { result.budget_exhausted = true; break; }
      used += [...content].length;
      result.results.push({ session_id: m.session_id, message_id: m.id, role: m.role, content, created_at: m.created_at, score: 0 });
    }
    result.total_found = messages.length; result.total_shown = result.results.length;
    result.note = result.budget_exhausted ? `Budget exhausted (${settings.memory_session_search_total_budget_chars} chars limit). ${messages.length - result.results.length} results omitted.` :
      `Retrieved from local chat history. Source: ${scope}.`;
    return result;
  }
  markdown(value: SessionSearchResponse): string {
    if (!value.results.length) return `*session_search: No results found for '${value.query}'*`;
    const lines = [`**Session Search Results** (query: '${value.query}', scope: ${value.scope})`, `Found ${value.total_found}, showing ${value.total_shown}.`, '',
      ...value.results.map((r, i) => `${i + 1}. [${r.role.toUpperCase()}] [${r.created_at.slice(0, 16).replace('T', ' ')}] ${r.content}`)];
    if (value.budget_exhausted) lines.push(`\n*Note: ${value.note}*`); return lines.join('\n');
  }
}
