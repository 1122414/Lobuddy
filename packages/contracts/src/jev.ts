import { z } from 'zod';
import { ChoiceAnswerSchema } from './models.js';
import { unicodeString } from './values.js';
export const JevContextSchema = z.strictObject({ notification: unicodeString({ max: 600 }),goal: unicodeString({ max: 600 }),
  recent_delivered: z.array(unicodeString({ max: 300 })).max(3) });
export type JevContext = z.infer<typeof JevContextSchema>;
export const VerifiedChoiceSchema = ChoiceAnswerSchema.superRefine((value,context) => {
  const keys = Object.keys(value.probabilities).sort();
  if (JSON.stringify(keys) !== '["no","unknown","yes"]') { context.addIssue({ code: 'custom',message: 'Invalid choice keys' }); return; }
  const values = Object.values(value.probabilities), peak = Math.max(...values);
  if (Math.abs(values.reduce((total,item) => total + item,0) - 1) > 0.01 || value.probabilities[value.choice]! < peak ||
    Math.abs(value.confidence - (peak - 1 / 3) / (2 / 3)) > 0.02) context.addIssue({ code: 'custom',message: 'Inconsistent choice confidence' });
});
export const JevResponseSchema = z.strictObject({ model: unicodeString({ max: 80 }).regex(/^jev-[a-zA-Z0-9.\-]+$(?![\s\S])/u),
  answers: z.strictObject({ relevant: VerifiedChoiceSchema,time_sensitive: VerifiedChoiceSchema,duplicate: VerifiedChoiceSchema }),
  usage: z.strictObject({ input_tokens: z.number().int().safe().min(0),output_tokens: z.number().int().safe().min(0) }) });
export type JevResponse = z.infer<typeof JevResponseSchema>;
