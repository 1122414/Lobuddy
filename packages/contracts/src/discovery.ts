import { z } from 'zod';
import { unicodeString } from './values.js';

export const DiscoveryRepositorySchema = z.string().trim().toLowerCase().max(160)
  .regex(/^[a-z0-9](?:[a-z0-9-]{0,38})\/[a-z0-9_.-]{1,100}$/u)
  .refine(value => !value.endsWith('/.') && !value.endsWith('/..'));
export const DiscoveryPolicySchema = z.strictObject({
  revision: z.number().int().safe().nonnegative().default(0),
  enabled: z.boolean().default(false),
  interests: z.array(unicodeString({ min: 1,max: 40 }).transform(value => value.trim())
    .refine(value => Boolean(value) && !/[\u0000-\u001f\u007f]/u.test(value))).max(6).default([]),
  repositories: z.array(DiscoveryRepositorySchema).max(3).default([]),
}).refine(value => new Set(value.repositories).size === value.repositories.length && new Set(value.interests).size === value.interests.length,
  '兴趣和项目不能重复').refine(value => !value.enabled || value.repositories.length > 0 && value.interests.length > 0,
  '启用前请填写兴趣和公开项目');
export type DiscoveryPolicy = z.infer<typeof DiscoveryPolicySchema>;
const timestamp = z.number().finite().nonnegative();
export const DiscoveryItemSchema = z.strictObject({
  id: z.string().regex(/^[a-f0-9]{64}$/u),repository: DiscoveryRepositorySchema,
  title: unicodeString({ min: 1,max: 200 }),text: unicodeString({ max: 1800 }),
  url: z.string().max(1000).regex(/^https:\/\/github\.com\/[a-z0-9-]+\/[a-z0-9_.-]+\/releases\/tag\/[^\s?#]+$/u),
  published_at: timestamp,checked_at: timestamp,expires_at: timestamp,
}).refine(value => value.expires_at === value.published_at + 7 * 86400 && value.checked_at >= value.published_at && value.checked_at < value.expires_at,
  '资讯时间范围无效');
export type DiscoveryItem = z.infer<typeof DiscoveryItemSchema>;
export const DiscoveryAttemptSchema = z.strictObject({
  repository: DiscoveryRepositorySchema,at: timestamp,next_at: timestamp,
  status: z.enum(['reading','ready','empty','unavailable','interrupted']),
});
export const DiscoveryStateSchema = z.strictObject({
  version: z.literal(1).default(1),policy: DiscoveryPolicySchema.default(() => DiscoveryPolicySchema.parse({})),
  day: z.string().regex(/^$|^\d{4}-\d{2}-\d{2}$/u).default(''),
  used: z.number().int().min(0).max(6).default(0),
  attempts: z.array(DiscoveryAttemptSchema).max(30).default([]),items: z.array(DiscoveryItemSchema).max(30).default([]),
  last_request: z.string().max(128).default(''),last_fingerprint: z.string().max(64).default(''),
});
export const DiscoveryViewSchema = z.strictObject({
  policy: DiscoveryPolicySchema,items: z.array(DiscoveryItemSchema).max(30),attempts: z.array(DiscoveryAttemptSchema).max(3),
  used: z.number().int().min(0).max(6),daily_limit: z.literal(6),reading: z.boolean(),
});
export type DiscoveryView = z.infer<typeof DiscoveryViewSchema>;
