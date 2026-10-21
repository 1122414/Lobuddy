import { z } from 'zod';
const sequence = z.number().int().safe().nonnegative();
export const SpeechCommandSchema = z.discriminatedUnion('kind',[
  z.strictObject({ kind: z.literal('check') }),z.strictObject({ kind: z.literal('download') }),
  z.strictObject({ kind: z.literal('start'),silence_ms: z.number().int().min(300).max(2000),generation: sequence }),
  z.strictObject({ kind: z.literal('frame'),generation: sequence,pcm: z.string().length(1368).regex(/^[A-Za-z0-9+/]{1366}==$/) }),
  z.strictObject({ kind: z.literal('stop') }),
]);
export type SpeechCommand = z.infer<typeof SpeechCommandSchema>;
export const SpeechRequestSchema = z.strictObject({ id: z.string().uuid(),command: SpeechCommandSchema });
export const SpeechEventSchema = z.strictObject({ kind: z.enum(['speech','transcript','error','overload']),generation: sequence,
  round: sequence,text: z.string().max(4000).default('') });
export type SpeechEvent = z.infer<typeof SpeechEventSchema>;
export const SpeechReplySchema = z.discriminatedUnion('kind',[
  z.strictObject({ kind: z.literal('booted') }),
  z.strictObject({ kind: z.literal('reply'),id: z.string().uuid(),ok: z.boolean(),ready: z.boolean().default(false) }),
  z.strictObject({ kind: z.literal('event'),event: SpeechEventSchema }),
  z.strictObject({ kind: z.literal('fault') }),
]);
export interface SpeechDriver {
  event: (event: SpeechEvent) => void;
  fault: () => void;
  request(command: SpeechCommand): Promise<boolean>;
  close(): Promise<void>;
}
