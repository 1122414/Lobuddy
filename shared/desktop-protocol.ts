// UI types come directly from the validated TypeScript contracts.
export type * from '@lobuddy/contracts' with { 'resolution-mode': 'import' };
import type { ParametersByMethod, MemoryItemSchema, SkillDetailSchema } from '@lobuddy/contracts' with { 'resolution-mode': 'import' };
import type { z } from 'zod';
// Editable drafts omit fields supplied by the service; returned records retain output types.
export type CompanionPreferences = ParametersByMethod['companion.save'];
export type CompanionPolicy = ParametersByMethod['companionship.configure'];
export type DelegationSpec = ParametersByMethod['delegation.create'];
export type SourceShare = ParametersByMethod['source.share'];
export type MemoryItem = z.input<typeof MemoryItemSchema>;
export type SkillDetail = z.input<typeof SkillDetailSchema>;
