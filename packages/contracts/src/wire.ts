import { z } from 'zod';
import { METHOD_NAMES } from './requests.js';
import { ServiceEventSchema } from './models.js';
import { unicodeString } from './values.js';

export const PROTOCOL_VERSION = 2 as const;
export const MAX_FRAME_BYTES = 1024 * 1024;
const identity = unicodeString({ min: 1, max: 128 });
const instance = z.uuid();
export const MethodSchema = z.enum(METHOD_NAMES as [typeof METHOD_NAMES[number], ...typeof METHOD_NAMES[number][]]);
export const ErrorCodeSchema = z.enum(['invalid_request', 'unsupported_method', 'id_conflict',
  'not_ready', 'unavailable', 'cancelled', 'timeout', 'internal_error']);
export type ErrorCode = z.infer<typeof ErrorCodeSchema>;
export const HelloSchema = z.strictObject({ kind: z.literal('hello'), protocol: z.literal(PROTOCOL_VERSION), client_id: identity });
export const ReadySchema = z.strictObject({ kind: z.literal('ready'), protocol: z.literal(PROTOCOL_VERSION),
  instance_id: instance, capabilities: z.array(identity), methods: z.array(MethodSchema), sequence: z.number().int().nonnegative().safe() });
export const RequestSchema = z.strictObject({ kind: z.literal('request'), protocol: z.literal(PROTOCOL_VERSION),
  instance_id: instance, jsonrpc: z.literal('2.0'), id: identity, method: MethodSchema,
  params: z.record(z.string(), z.json()) });
export type Request = z.infer<typeof RequestSchema>;
export const ResponseSchema = z.strictObject({ kind: z.literal('response'), instance_id: instance,
  jsonrpc: z.literal('2.0'), id: identity,
  outcome: z.discriminatedUnion('ok', [z.strictObject({ ok: z.literal(true), result: z.json() }),
    z.strictObject({ ok: z.literal(false), code: ErrorCodeSchema })]) });
export const EventFrameSchema = z.strictObject({ kind: z.literal('event'), instance_id: instance, event: ServiceEventSchema });
export const CloseSchema = z.strictObject({ kind: z.literal('close'), instance_id: instance });
export const ClosedSchema = z.strictObject({ kind: z.literal('closed'), instance_id: instance });
export const ClientFrameSchema = z.discriminatedUnion('kind', [HelloSchema, RequestSchema, CloseSchema]);
export const ServerFrameSchema = z.discriminatedUnion('kind', [ReadySchema, ResponseSchema, EventFrameSchema, ClosedSchema]);
export type ClientFrame = z.infer<typeof ClientFrameSchema>;
export type ServerFrame = z.infer<typeof ServerFrameSchema>;

export function assertFrameSize(value: unknown): void {
  const serialized = JSON.stringify(value);
  if (serialized === undefined || Buffer.byteLength(serialized, 'utf8') > MAX_FRAME_BYTES) throw new Error('Protocol frame exceeds limit');
}
