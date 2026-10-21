import { z } from 'zod';
export const BridgeReadySchema = z.strictObject({ port: z.int().min(1).max(65535), pid: z.int().positive(), protocol: z.literal(1) });
export const BridgeEventSchema = z.strictObject({ sessionId: z.string().min(1).max(128),
  taskId: z.string().min(1).max(128), turnId: z.string().min(1).max(128), sequence: z.int().positive(),
  kind: z.enum(['turn.started', 'turn.completed', 'turn.cancelled', 'turn.failed', 'text.delta', 'text.final', 'tool.request', 'usage']),
  data: z.record(z.string(), z.json()) });
export type BridgeEvent = z.infer<typeof BridgeEventSchema>;
export const BridgeResponseSchema = z.strictObject({ jsonrpc: z.literal('2.0'), id: z.string(), result: z.json().optional(),
  error: z.object({ code: z.number(), message: z.string(), data: z.object({ kind: z.string() }).optional() }).optional() })
  .refine(value => (value.result !== undefined) !== (value.error !== undefined));
