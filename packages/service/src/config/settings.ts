import { RuntimeSettingsSchema, SETTINGS_DESCRIPTORS, JsonRecordSchema, type RuntimeSettings, type SettingsView, type SettingsPatch } from '@lobuddy/contracts';
import { Store, StorageError } from '../storage/database.js';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { parseEnv } from 'node:util';
export const SECRET_FIELDS = ['llm_api_key', 'llm_multimodal_api_key', 'fish_api_key', 'typesafe_api_key'] as const;
export type SecretField = typeof SECRET_FIELDS[number];
const FIXED = new Set(['data_dir', 'workspace_path', 'logs_dir', 'nanobot_config_path', 'skill_archive_dir',
  'memory_profile_file', 'memory_system_profile_file', 'memory_project_profile_file', 'guardrails_enabled', 'execution_governance_enabled']);
const forbidden = (key: string) => FIXED.has(key) || SECRET_FIELDS.includes(key as SecretField);

function decode(key: keyof RuntimeSettings, raw: unknown): unknown {
  const definition = SETTINGS_DESCRIPTORS[key] as { type?: string; anyOf?: { type: string }[] };
  if (definition.type === 'boolean' && (raw === 0 || raw === 1)) return Boolean(raw);
  if ((definition.type === 'number' || definition.type === 'integer') && typeof raw === 'boolean') return Number(raw);
  if (typeof raw !== 'string' || definition.type === 'string' || definition.anyOf?.some(item => item.type === 'string')) return raw;
  if (definition.type === 'boolean') {
    if (['1', 'true', 't', 'yes', 'y', 'on'].includes(raw.toLowerCase())) return true;
    if (['0', 'false', 'f', 'no', 'n', 'off'].includes(raw.toLowerCase())) return false;
    return raw;
  }
  if ((definition.type === 'number' || definition.type === 'integer') && /^\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?\s*$/.test(raw)) return Number(raw);
  return raw;
}
export function parseEnvironment(text: string, explicit: NodeJS.ProcessEnv = {}): Record<string, string> {
  const parsed = parseEnv(text);
  const result: Record<string, string> = {};
  for (const [key, raw] of Object.entries(parsed)) {
    if (raw === undefined) continue;
    result[key] = raw.replace(/\$\{([a-zA-Z_][a-zA-Z_0-9]*)(?::-([^}]*))?\}/g,
      (_match, name: string, fallback: string | undefined) => explicit[name] ?? result[name] ?? fallback ?? '');
  }
  for (const [key, value] of Object.entries(explicit)) if (value !== undefined) result[key] = value;
  return result;
}
export function runtimeSettings(options: { data: string; workspace: string; logs: string;
  environment?: NodeJS.ProcessEnv; dotenv?: string }): RuntimeSettings {
  const environment = parseEnvironment(options.dotenv ?? '', options.environment ?? {});
  const values: Record<string, unknown> = {};
  for (const [key, raw] of Object.entries(environment)) {
    const field = key.toLowerCase() as keyof RuntimeSettings;
    if (Object.hasOwn(SETTINGS_DESCRIPTORS, field) && !forbidden(field)) values[field] = decode(field, raw);
  }
  // Main owns secrets. Never persist or expose incoming environment credentials here.
  return RuntimeSettingsSchema.parse({ ...values, llm_api_key: '', fish_api_key: '', typesafe_api_key: '', llm_multimodal_api_key: null,
    data_dir: resolve(options.data), workspace_path: resolve(options.workspace), logs_dir: resolve(options.logs),
    nanobot_config_path: resolve(homedir(), '.nanobot/config.json'), skill_archive_dir: resolve(options.data, 'skills/archive'),
    memory_profile_file: resolve(options.data, 'memory/USER.md'), memory_system_profile_file: resolve(options.data, 'memory/SYSTEM.md'),
    memory_project_profile_file: resolve(options.data, 'memory/PROJECT.md'), guardrails_enabled: true, execution_governance_enabled: true });
}
export class SettingsRepository {
  restartRequired = false;
  private credentials: Partial<Record<SecretField, boolean>> = {};
  constructor(private readonly store: Store, private readonly defaults: RuntimeSettings) {}
  effective(): RuntimeSettings {
    const values: Record<string, unknown> = { ...this.defaults };
    for (const row of this.store.connection.prepare('SELECT key,value FROM app_settings').all()) {
      const key = String(row.key) as keyof RuntimeSettings;
      if (Object.hasOwn(SETTINGS_DESCRIPTORS, key) && !forbidden(key)) values[key] = decode(key, row.value);
    }
    return RuntimeSettingsSchema.parse(values);
  }
  setCredentialStatus(status: Partial<Record<SecretField, boolean>>): void { this.credentials = { ...status }; }
  view(): SettingsView {
    const effective = this.effective();
    const visible = Object.entries(effective).filter(([key]) => !forbidden(key));
    return { values: Object.fromEntries(visible), schema_fields: JsonRecordSchema.parse(Object.fromEntries(visible.map(([key]) => [key, SETTINGS_DESCRIPTORS[key as keyof RuntimeSettings]]))),
      credentials: Object.fromEntries(SECRET_FIELDS.map(key => [key, Boolean(this.credentials[key])])), restart_required: this.restartRequired };
  }
  patch(input: SettingsPatch): SettingsView {
    for (const key of Object.keys(input.values)) if (forbidden(key) || !Object.hasOwn(SETTINGS_DESCRIPTORS, key)) throw new StorageError('此设置需要专用迁移或凭据入口');
    const normalized = Object.fromEntries(Object.entries(input.values).map(([key, value]) => [key, decode(key as keyof RuntimeSettings, value)]));
    const settings = RuntimeSettingsSchema.parse({ ...this.effective(), ...normalized });
    this.store.transaction(() => {
      for (const key of Object.keys(input.values) as (keyof RuntimeSettings)[]) {
        const value = settings[key];
        this.store.run(`INSERT INTO app_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at`,
          key, typeof value === 'string' ? value : JSON.stringify(value), new Date().toISOString());
      }
      if ('pet_name' in input.values) this.store.run("UPDATE pet_state SET name=? WHERE id='default'", settings.pet_name);
    });
    this.restartRequired = true; return this.view();
  }
}
