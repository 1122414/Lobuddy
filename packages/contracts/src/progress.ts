import { z } from 'zod';
export const PetProgressEventSchema = z.object({ exp_gained: z.int().nonnegative().default(0),
  current_exp: z.int().nonnegative().default(0), required_exp: z.int().nonnegative().default(0),
  level_up: z.boolean().default(false), new_level: z.int().nullable().default(null), new_stage: z.int().nullable().default(null),
  personality_adjustments: z.record(z.string(), z.number()).nullable().default(null),
  unlocked_abilities: z.array(z.tuple([z.string(), z.string()])).default([]) });
export type PetProgressEvent = z.infer<typeof PetProgressEventSchema>;
export const ObservedUsageSchema = z.object({ inputTokens: z.int().nonnegative(), outputTokens: z.int().nonnegative(),
  cacheReadTokens: z.int().nonnegative().default(0), cacheWriteTokens: z.int().nonnegative().default(0) });
