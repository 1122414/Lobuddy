import { z } from 'zod';
import { unicodeString } from './values.js';

export const RelationProposalSchema = z.strictObject({
  kind: z.enum(['preference', 'shared', 'inferred', 'temporary']),
  key: unicodeString({ min: 1, max: 80 }), content: unicodeString({ min: 1, max: 1000 }),
  source_ids: z.array(z.string()).min(1).max(10),
  quote: unicodeString({ max: 1000 }).default(''),
  scope: z.enum(['global', 'session']).default('global'), sensitive: z.boolean().default(false),
});
export type RelationProposal = z.infer<typeof RelationProposalSchema>;
export const SummaryFactSchema = z.strictObject({
  kind: z.enum(['goal', 'decision', 'correction', 'pending', 'shared']),
  content: unicodeString({ min: 1, max: 300 }), source_ids: z.array(z.string()).min(1).max(5),
});
export type SummaryFact = z.infer<typeof SummaryFactSchema>;
export const RelationAnalysisSchema = z.strictObject({
  memories: z.array(RelationProposalSchema).max(5).default([]),
  summary: z.array(SummaryFactSchema).max(8).default([]),
});
