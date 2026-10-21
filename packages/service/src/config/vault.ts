// Instantiate only in Electron main. The business process receives per-call values in memory.
import { CredentialEnvelopeSchema, SecretFieldSchema } from '@lobuddy/contracts';
import { createHash } from 'node:crypto';
import { hostname, userInfo } from 'node:os';
import { atomicPrivateWrite, readPrivate } from '../storage/files.js';
import { SECRET_FIELDS, parseEnvironment, type SecretField } from './settings.js';
export interface Cipher {
  available(): boolean;
  encrypt(value: string): Buffer;
  decrypt(value: Buffer): string;
}
export class CredentialError extends Error {
  constructor() { super('系统凭据存储不可用或校验失败；原凭据已保留，未使用明文回退'); }
}
export class CredentialVault {
  private writing: Promise<void> = Promise.resolve();
  constructor(private readonly path: string, private readonly cipher: Cipher) {}
  private async envelope() {
    if (!this.cipher.available()) throw new CredentialError();
    try { return CredentialEnvelopeSchema.parse(JSON.parse((await readPrivate(this.path, 500000)).toString())); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return { format: 1 as const, entries: {} as Partial<Record<SecretField, string>> }; throw new CredentialError(); }
  }
  async get(account: SecretField): Promise<string | undefined> {
    SecretFieldSchema.parse(account);
    try {
      const value = (await this.envelope()).entries[account];
      if (value === undefined) return undefined;
      if (Buffer.from(value, 'base64').toString('base64') !== value) throw new CredentialError();
      return this.cipher.decrypt(Buffer.from(value, 'base64'));
    } catch { throw new CredentialError(); }
  }
  set(account: SecretField, value: string): Promise<void> {
    const write = this.writing.then(async () => {
      try {
        SecretFieldSchema.parse(account);
        if (!value || [...value].length > 16000 || value.includes('\0')) throw new CredentialError();
        const previous = await this.envelope();
        const encrypted = this.cipher.encrypt(value);
        if (this.cipher.decrypt(encrypted) !== value) throw new CredentialError();
        const next = { format: 1, entries: { ...previous.entries, [account]: encrypted.toString('base64') } };
        await atomicPrivateWrite(this.path, Buffer.from(JSON.stringify(next)));
        try { if (await this.get(account) !== value) throw new CredentialError(); }
        catch { await atomicPrivateWrite(this.path, Buffer.from(JSON.stringify(previous))); throw new CredentialError(); }
      } catch { throw new CredentialError(); }
    });
    this.writing = write.catch(() => {}); return write;
  }
  async status(): Promise<Record<SecretField, boolean>> {
    const result = {} as Record<SecretField, boolean>;
    for (const field of SECRET_FIELDS) result[field] = Boolean(await this.get(field));
    return result;
  }
}
// Compatibility decoder only. New writes always use the injected system cipher.
export function decodeLegacySecret(value: string, identity = { user: userInfo().username, host: hostname() }): string {
  if (!value.startsWith('enc:v1:')) return value;
  try {
    const base64 = value.slice(7), bytes = Buffer.from(base64, 'base64');
    if (bytes.toString('base64') !== base64) throw new CredentialError();
    const key = createHash('sha256').update(`${identity.user}@${identity.host}:lobuddy_v1`).digest();
    const decoded = Buffer.from(bytes.map((byte, index) => byte ^ key[index % key.length]!));
    return new TextDecoder('utf-8', { fatal: true }).decode(decoded);
  } catch { throw new CredentialError(); }
}
export async function migrateCredentials(options: { vault: CredentialVault; dotenv?: string; environment?: NodeJS.ProcessEnv;
  database?: Partial<Record<SecretField, string>>; legacyKeychain: (account: SecretField) => Promise<string | undefined> }): Promise<Record<SecretField, boolean>> {
  const environment = parseEnvironment(options.dotenv ?? '', options.environment ?? {});
  for (const account of SECRET_FIELDS) {
    const explicit = environment[account.toUpperCase()] || environment[account];
    const value = explicit || await options.vault.get(account) || await options.legacyKeychain(account) || options.database?.[account];
    if (value) {
      const plaintext = decodeLegacySecret(value);
      await options.vault.set(account, plaintext);
      if (await options.vault.get(account) !== plaintext) throw new CredentialError();
    }
  }
  // Keep old .env, Keychain and original database untouched for the first-switch rollback.
  return options.vault.status();
}
