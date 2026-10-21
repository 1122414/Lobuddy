/** Main-only system cipher adapter. Never export stored values through preload. */
import { app, safeStorage } from 'electron';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import type { SecretField } from '@lobuddy/service' with { 'resolution-mode': 'import' };
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
    const details = error as { code?: unknown; killed?: boolean };
    const status = details.killed ? '授权等待超时' : typeof details.code === 'number' ? `系统状态 ${details.code}` : '系统不可用';
    throw new Error(`旧钥匙串读取失败（${status}）；原凭据保留，未使用明文回退`);
  }
}

export async function configureCredential(vault: Awaited<ReturnType<typeof openCredentialVault>>,account: string): Promise<{ saved: boolean }> {
  if (!accounts.has(account) || process.platform !== 'darwin') throw Error('凭据配置暂不支持当前平台');
  const labels: Record<string,string> = {llm_api_key:'模型服务',llm_multimodal_api_key:'图片模型',fish_api_key:'Fish Audio',typesafe_api_key:'Jev / TypeSafe'};
  const script = `try\nset result to display dialog "请输入 ${labels[account]} API Key，保存后重启 Lobuddy 生效。" default answer "" with hidden answer buttons {"取消", "保存"} default button "保存"\nreturn text returned of result\non error number -128\nreturn ""\nend try`;
  try {
    const {stdout}=await execute('/usr/bin/osascript',['-e',script],{timeout:120000,maxBuffer:20000,env:{PATH:'/usr/bin:/bin'}});
    const value=stdout.trim();if(!value)return {saved:false};
    await vault.set(account as SecretField,value);return {saved:true};
  } catch {throw Error('凭据未保存，请重试；原凭据保留');}
}
