import { z } from 'zod';
import { unicodeString } from './values.js';

const id = z.string().min(1).max(128), time = z.number().finite().nonnegative();
export const CarePolicySchema = z.strictObject({ revision: z.number().int().nonnegative().default(0),enabled: z.boolean().default(true),
  timezone: z.string().max(100).refine(value => { try { new Intl.DateTimeFormat('en',{ timeZone: value }); return true; } catch { return false; } }),
  start_hour: z.number().int().min(0).max(23).default(9),end_hour: z.number().int().min(1).max(24).default(23),
}).refine(value => value.start_hour < value.end_hour,'主动时段必须在同一天内');
export type CarePolicy = z.infer<typeof CarePolicySchema>;
export const CareSourceClockSchema = z.strictObject({at: time,timezone: CarePolicySchema.shape.timezone});
export const CareProposalSchema = z.strictObject({ source_id: id,quote: unicodeString({ min: 4,max: 500 }),
  subject: unicodeString({ min: 2,max: 80 }) });
export type CareProposal = z.infer<typeof CareProposalSchema>;
export const CareItemSchema = z.strictObject({ id,memory_id: id,source_id: id,source_revision: z.string().min(1).max(128),
  session_id: id,project_id: z.string().max(128),title: unicodeString({ min: 2,max: 80 }),
  revision: z.number().int().positive(),status: z.enum(['preparing','active','deferred','paused','closed','invalid']),
  next_at: time,expires_at: time,unanswered: z.number().int().min(0).max(2),last_presented_at: time,
  last_response_id: z.string().max(128),created_at: time,updated_at: time });
export type CareItem = z.infer<typeof CareItemSchema>;
export const CareViewSchema = CareItemSchema.extend({ fact: unicodeString({ max: 500 }) });
export const CareConfigureSchema = CarePolicySchema;
export const CareUpdateSchema = z.strictObject({ id,revision: z.number().int().positive(),
  action: z.enum(['defer','pause','resume','close']),until: time.optional() });
export const CarePresetSchema = z.strictObject({ apply: z.literal(true),revision: z.number().int().nonnegative().optional() });
export const CarePresentedSchema = z.strictObject({ notice_id: id });
