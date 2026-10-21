import { z } from 'zod';
import { CompanionNoticeSchema } from './models.js';
import { unicodeString } from './values.js';
export const CompanionPolicyStateSchema = z.object({
  day: z.string().default(''), used: z.number().int().safe().default(0), last_shown: z.number().default(0),
  last_topic_id: z.string().default(''), cooldown_until: z.number().default(0), pending: z.string().default(''),
  pending_at: z.number().default(0), pending_expires: z.number().default(0), notice: CompanionNoticeSchema.nullable().default(null),
});
export const TopicChoiceSchema = z.object({ topic_id: z.string(), memory_id: z.string(), revision: z.string(), text: z.string() });
export type TopicChoice = z.infer<typeof TopicChoiceSchema>;
export const InvitationDraftSchema = z.strictObject({ source_id: z.string(), quote: unicodeString({ min: 1, max: 60 }),
  opening: z.enum(['你之前说', '我还记得你说', '想到你之前说的']),
  closing: z.enum(['想接着聊时，我在。', '不用急着决定。', '先陪你待一会儿。', '我们可以慢慢来。']),
});
export const InvitationBodySchema = InvitationDraftSchema.omit({ source_id: true, quote: true }).extend({
  start: z.number().int().safe().min(0), length: z.number().int().safe().min(1).max(60),
});
