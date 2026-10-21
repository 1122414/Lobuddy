import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createHash, createCipheriv, createDecipheriv, randomBytes } from 'node:crypto';
import { Store } from './storage/database.js';
import { runtimeSettings, SettingsRepository, parseEnvironment } from './config/settings.js';
import { CredentialVault, migrateCredentials, decodeLegacySecret, type Cipher } from './config/vault.js';

function cipher(): Cipher {
  const key = randomBytes(32);
  return { available: () => true,
    encrypt: value => { const iv = randomBytes(12); const enc = createCipheriv('aes-256-gcm', key, iv);
      const bytes = Buffer.concat([enc.update(value, 'utf8'), enc.final()]); return Buffer.concat([iv, enc.getAuthTag(), bytes]); },
    decrypt: value => { const dec = createDecipheriv('aes-256-gcm', key, value.subarray(0, 12)); dec.setAuthTag(value.subarray(12, 28));
      return Buffer.concat([dec.update(value.subarray(28)), dec.final()]).toString('utf8'); } };
}
test('settings preserve typed DB precedence, fixed governance and secret-free UI descriptors', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-settings-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  try {
    const defaults = runtimeSettings({ data: root, workspace: join(root, 'workspace'), logs: join(root, 'logs'),
      dotenv: 'LLM_MODEL=first\nFOCUS_DEFAULT_MINUTES=35\nGUARDRAILS_ENABLED=false\nLLM_API_KEY=synthetic-not-visible',
      environment: { LLM_MODEL: 'explicit' } });
    assert.equal(defaults.llm_model, 'explicit'); assert.equal(defaults.focus_default_minutes, 35);
    assert.equal(defaults.guardrails_enabled, true); assert.equal(defaults.llm_api_key, '');
    const repository = new SettingsRepository(store, defaults);
    const view = repository.patch({ values: { llm_model: 'stored', focus_default_minutes: 45, memory_profile_enabled: false } });
    assert.equal(view.values.llm_model, 'stored'); assert.equal(view.values.memory_profile_enabled, false);
    assert.equal(repository.effective().focus_default_minutes, 45);
    assert.equal(JSON.stringify(view).includes('synthetic-not-visible'), false);
    assert.equal(Object.hasOwn(view.values, 'llm_api_key'), false); assert.equal(Object.hasOwn(view.schema_fields, 'llm_api_key'), false);
    assert.throws(() => repository.patch({ values: { guardrails_enabled: false } }));
    assert.throws(() => repository.patch({ values: { fish_api_key: 'blocked' } }));
    assert.throws(() => repository.patch({ values: { task_timeout: -1, llm_model: 'must-not-save' } }));
    assert.equal(repository.effective().llm_model, 'stored');
  } finally { store.close(); await rm(root, { recursive: true, force: true }); }
});
test('dotenv multiline and explicit per-field credentials remain independent', async () => {
  assert.deepEqual(parseEnvironment('PREFIX=fish\nNAME=${PREFIX}-voice\nMULTI="first\nsecond"', { PREFIX: 'explicit' }),
    { PREFIX: 'explicit', NAME: 'explicit-voice', MULTI: 'first\nsecond' });
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-credentials-'));
  try {
    const native = cipher(), vault = new CredentialVault(join(root, 'vault.json'), native);
    const old = { fish_api_key: 'synthetic-old-fish', typesafe_api_key: 'synthetic-jev' };
    await migrateCredentials({ vault, environment: { LLM_API_KEY: 'synthetic-llm', LLM_MULTIMODAL_API_KEY: 'synthetic-vision', FISH_API_KEY: 'synthetic-new-fish' },
      legacyKeychain: async account => old[account as keyof typeof old] });
    assert.equal(await vault.get('llm_api_key'), 'synthetic-llm');
    assert.equal(await vault.get('fish_api_key'), 'synthetic-new-fish');
    assert.equal(await vault.get('typesafe_api_key'), 'synthetic-jev');
    assert.equal(await vault.get('llm_multimodal_api_key'), 'synthetic-vision');
    assert.equal(old.fish_api_key, 'synthetic-old-fish');
    const file = await readFile(join(root, 'vault.json'));
    for (const value of ['synthetic-llm', 'synthetic-vision', 'synthetic-new-fish', 'synthetic-jev']) assert.equal(file.includes(Buffer.from(value)), false);
    const reopened = new CredentialVault(join(root, 'vault.json'), native);
    assert.equal(await reopened.get('llm_api_key'), 'synthetic-llm');
    assert.equal(await reopened.get('llm_multimodal_api_key'), 'synthetic-vision');
    assert.equal((await stat(join(root, 'vault.json'))).mode & 0o777, 0o600);
    await Promise.all([vault.set('fish_api_key', 'concurrent-fish'), vault.set('typesafe_api_key', 'concurrent-jev')]);
    assert.equal(await vault.get('fish_api_key'), 'concurrent-fish'); assert.equal(await vault.get('typesafe_api_key'), 'concurrent-jev');
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('native cipher unavailable, readback failure and symlink never fall back to plaintext', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-credential-fault-'));
  try {
    const path = join(root, 'vault.json'); const native = cipher();
    const vault = new CredentialVault(path, native); await vault.set('llm_api_key', 'synthetic-existing');
    const before = await readFile(path);
    const unavailable = new CredentialVault(path, { ...native, available: () => false });
    await assert.rejects(unavailable.set('llm_api_key', 'must-not-persist'), /未使用明文/);
    const invalid = new CredentialVault(path, { ...native, decrypt: () => 'different' });
    await assert.rejects(invalid.set('llm_api_key', 'must-not-persist'), /校验失败/);
    assert.deepEqual(await readFile(path), before);
    await symlink(path, join(root, 'alias'));
    await assert.rejects(new CredentialVault(join(root, 'alias'), native).set('fish_api_key', 'must-not-persist'));
    assert.deepEqual(await readFile(path), before);
  } finally { await rm(root, { recursive: true, force: true }); }
});
test('enc:v1 is decoded only for compatible historical identity', () => {
  const identity = { user: 'synthetic', host: 'fixture.local' }, value = 'synthetic-legacy-key';
  const key = createHash('sha256').update('synthetic@fixture.local:lobuddy_v1').digest();
  const encrypted = Buffer.from(Buffer.from(value).map((byte, index) => byte ^ key[index % key.length]!));
  assert.equal(decodeLegacySecret('enc:v1:' + encrypted.toString('base64'), identity), value);
  assert.throws(() => decodeLegacySecret('enc:v1:not base64', identity));
});
test('configuration defaults and coercion match frozen Python settings outcomes', async () => {
  const fixture = JSON.parse(await readFile(new URL('../../../migration/fixtures/settings-cases.json', import.meta.url), 'utf8')) as {
    defaults: Record<string, unknown>; cases: { field: string; input: string | number | boolean; accepted: boolean; value?: unknown }[] };
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-config-oracle-'));
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  try {
    const repository = new SettingsRepository(store, runtimeSettings({ data: root, workspace: root, logs: root }));
    const initial = repository.view();
    for (const [field, value] of Object.entries(fixture.defaults)) assert.deepEqual(initial.values[field], value, field);
    for (const sample of fixture.cases) {
      if (sample.accepted) assert.deepEqual(repository.patch({ values: { [sample.field]: sample.input } }).values[sample.field], sample.value, sample.field);
      else assert.throws(() => repository.patch({ values: { [sample.field]: sample.input } }), sample.field);
    }
  } finally { store.close(); await rm(root, { recursive: true, force: true }); }
});
