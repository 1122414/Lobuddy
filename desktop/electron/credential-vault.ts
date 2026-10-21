/** Main-only system cipher adapter. Never export stored values through preload. */
import { app, safeStorage } from 'electron';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute = promisify(execFile);
const accounts = new Set(['llm_api_key', 'llm_multimodal_api_key', 'fish_api_key', 'typesafe_api_key']);

export async function openCredentialVault(path: string) {
  await app.whenReady();
  const { CredentialVault } = await import('@lobuddy/service');
  return new CredentialVault(path, {
    available: () => safeStorage.isEncryptionAvailable() &&
      (process.platform !== 'linux' || safeStorage.getSelectedStorageBackend() !== 'basic_text'),
    encrypt: value => safeStorage.encryptString(value),
    decrypt: value => safeStorage.decryptString(value),
  });
}
export async function readLegacyCredential(account: string): Promise<string | undefined> {
  if (!accounts.has(account) || process.platform !== 'darwin') throw new Error('当前系统无法迁移旧凭据');
  try {
    // Only the public service/account identifiers occur in argv. Never log stdout/stderr.
    const { stdout } = await execute('/usr/bin/security', ['find-generic-password', '-s', 'com.lobuddy.desktop', '-a', account, '-w'],
      { timeout: 60_000, maxBuffer: 100000, env: { PATH: '/usr/bin:/bin' } });
    return stdout.endsWith('\n') ? stdout.slice(0, -1) : stdout;
  } catch (error) {
    if ((error as { code?: number }).code === 44) return undefined;
    throw new Error('旧钥匙串读取失败；原凭据保留，未使用明文回退');
  }
}
