import { z } from 'zod';
import { unicodeString } from './values.js';

export const InvitationDecisionSchema = z.discriminatedUnion('action', [
  z.strictObject({ action: z.literal('speak'), source_id: z.string().min(1).max(256),
    quote: unicodeString({ min: 2, max: 80 }), text: unicodeString({ min: 4, max: 140 }),
    alternative: z.strictObject({ quote: unicodeString({ min: 2, max: 80 }),text: unicodeString({ min: 4, max: 140 }) }).optional() }),
  z.strictObject({ action: z.literal('defer'), reason: z.enum(['too_soon','not_a_good_moment']) }),
  z.strictObject({ action: z.literal('pass'), reason: z.enum(['low_value','already_discussed','no_relevant_topic']) }),
]);
export const InvitationReviewSchema = z.strictObject({
  choice: z.union([z.literal(0),z.literal(1)]).default(0),
  clauses: z.array(z.strictObject({ kind: z.enum(['fact','opinion','hypothesis','question']),
    claim: unicodeString({ min: 1, max: 140 }), evidence: unicodeString({ min: 1, max: 160 }).nullable() })).min(1).max(8),
  grounded: z.boolean(), natural: z.boolean(), respectful: z.boolean(),
});
const identity = z.strictObject({ source_id: z.string().min(1).max(256), revision: z.string().min(1).max(128) });
const base = { version: z.literal(2), attempt: z.union([z.literal(0),z.literal(1)]) };
export const InvitationPlanSchema = z.discriminatedUnion('action', [
  z.strictObject({ ...base, action: z.literal('queued'), candidates: z.array(identity).min(1).max(6) }),
  z.strictObject({ ...base, action: z.literal('speak'), text: unicodeString({ min: 4, max: 140 }),
    start: z.number().int().safe().min(0), length: z.number().int().safe().min(2).max(80),
    activity: z.number().int().safe().min(0), reviewed: z.literal(true) }),
  z.strictObject({ ...base, action: z.literal('defer'), retry_at: z.number().finite().positive(), reason: z.string().max(100) }),
  z.strictObject({ ...base, action: z.literal('pass'), reason: z.string().max(100) }),
]);
export type InvitationPlan = z.infer<typeof InvitationPlanSchema>;
