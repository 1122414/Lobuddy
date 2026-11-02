import { z } from 'zod';
import { SETTINGS_DESCRIPTORS } from './settings.js';
export const BackupManifestSchema = z.strictObject({
  format: z.literal(1), identity: z.string().min(1).max(128), source_data: z.string(),
  source_workspace: z.string(), created_at: z.string(),
  files: z.record(z.string(), z.string().regex(/^[a-f0-9]{64}$/)),
});
export type BackupManifest = z.infer<typeof BackupManifestSchema>;
export const ImportMarkerSchema = z.strictObject({ backup_id: z.string(), manifest_sha256: z.string().regex(/^[a-f0-9]{64}$/), storage_version: z.union([z.literal(3),z.literal(4),z.literal(5)]) });
export const JsonRecordSchema = z.record(z.string(), z.json());
export const JsonStringListSchema = z.array(z.string());
export const SecretFieldSchema = z.enum(['llm_api_key', 'llm_multimodal_api_key', 'fish_api_key', 'typesafe_api_key']);
export const CredentialEnvelopeSchema = z.strictObject({ format: z.literal(1),
  entries: z.partialRecord(SecretFieldSchema, z.string().min(1).max(100000)) });
export const StorageStartupSchema = z.strictObject({ data: z.string().min(1).max(4096),
  workspace: z.string().min(1).max(4096), logs: z.string().min(1).max(4096), create: z.boolean().optional() });
export const EngineStartupSchema = z.strictObject({ binary: z.string().min(1).max(4096),
  binarySha256: z.string().regex(/^[a-f0-9]{64}$/), plugin: z.string().min(1).max(4096),
  applicationRoot: z.string().min(1).max(4096), apiKey: z.string().min(1).max(16384),
  baseUrl: z.string().min(1).max(4096), model: z.string().min(1).max(256) });
// Only the trusted main process may send this bootstrap frame; it is not an RPC method.
export const ServiceConnectSchema = z.strictObject({ kind: z.literal('connect'), storage: StorageStartupSchema.optional(),
  engine: EngineStartupSchema.optional(), credentials: z.partialRecord(SecretFieldSchema,z.string().max(16384)).optional(),
  config: z.record(z.string().regex(/^[A-Z][A-Z0-9_]{0,80}$/),z.string().max(20000)).refine(value =>
    Object.keys(value).every(key => Object.hasOwn(SETTINGS_DESCRIPTORS,key.toLowerCase()) && !SecretFieldSchema.safeParse(key.toLowerCase()).success),'Invalid public startup setting').optional(),
}).refine(value => (!value.engine && !value.credentials) || value.storage, 'Credentials and engine require storage');
