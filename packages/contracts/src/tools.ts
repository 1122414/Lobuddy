import { z } from 'zod';
import { unicodeString } from './values.js';
const text = (max: number, min = 1) => unicodeString({ min, max });
export const FileArgumentsSchema = z.strictObject({ path: text(4096), content: text(100000, 0).nullable().default(null) });
export const SearchArgumentsSchema = z.strictObject({ query: text(200), scope: z.enum(['current_session','all_sessions']).default('current_session') });
export const OrganizeArgumentsSchema = z.strictObject({ source: text(4096), output: text(4096), preview_id: text(128, 0).default('') });
export const DigestArgumentsSchema = z.strictObject({ sources: z.array(text(4096)).min(1).max(6), reuse_local_sources: z.boolean().default(false) });
export const MemoryArgumentsSchema = z.strictObject({ memory_type: z.enum(['user_profile','project_memory','episodic_memory','procedural_memory']),
  title: text(100, 0), content: text(2000), confidence: z.number().min(0).max(1) });
const request = <N extends string, S extends z.ZodType>(name: N, args: S) => z.strictObject({ callId: text(128), name: z.literal(name), arguments: args });
export const ToolRequestSchema = z.discriminatedUnion('name', [
  request('lobuddy_read_file', FileArgumentsSchema), request('lobuddy_write_file', FileArgumentsSchema),
  request('lobuddy_local_open', FileArgumentsSchema), request('lobuddy_local_resolve', SearchArgumentsSchema),
  request('lobuddy_session_search', SearchArgumentsSchema), request('lobuddy_memory_propose', MemoryArgumentsSchema),
  request('lobuddy_skill_read', z.strictObject({ skill_id: text(128) })),
  request('lobuddy_exec', z.strictObject({ command: text(4000) })), request('lobuddy_web_fetch', z.strictObject({ url: text(4096) })),
  request('lobuddy_web_search', SearchArgumentsSchema), request('lobuddy_organize', OrganizeArgumentsSchema), request('lobuddy_digest', DigestArgumentsSchema),
]);
export type ToolRequest = z.infer<typeof ToolRequestSchema>;
export type OrganizeArguments = z.infer<typeof OrganizeArgumentsSchema>;
export type DigestArguments = z.infer<typeof DigestArgumentsSchema>;
