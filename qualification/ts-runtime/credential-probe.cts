import { safeStorage } from 'electron';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { writeFile, readFile, rename, stat } from 'node:fs/promises';
import { join } from 'node:path';
import assert from 'node:assert/strict';

async function security(args: string[], input?: string): Promise<{ code: number | null; stdout: Buffer }> {
  return new Promise((done, reject) => {
    const child = spawn('/usr/bin/security', args, { stdio: ['pipe', 'pipe', 'ignore'],
      env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME } });
    const chunks: Buffer[] = [];
    let size = 0;
    const timeout = setTimeout(() => child.kill('SIGTERM'), 15_000);
    child.stdout.on('data', (bytes: Buffer) => {
      size += bytes.length;
      if (size > 65_536) child.kill('SIGTERM'); else chunks.push(bytes);
    });
    child.once('error', (error) => { clearTimeout(timeout); reject(error); });
    child.once('close', code => { clearTimeout(timeout); done({ code, stdout: Buffer.concat(chunks) }); });
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  });
}

export async function qualifyCredentials(directory: string): Promise<string> {
  assert.ok(safeStorage.isEncryptionAvailable());
  const service = 'com.lobuddy.desktop.qualification';
  const account = `synthetic-${randomUUID()}`;
  const secret = `synthetic-${randomUUID()}`;
  const query = ['-s', service, '-a', account];
  try {
    // Even this synthetic value goes through stdin, never process arguments.
    await security(['-i'], `add-generic-password -s ${service} -a ${account} -w ${secret}\nquit\n`);
    const source = await security(['find-generic-password', ...query, '-w']);
    assert.equal(source.code, 0, 'Synthetic source Keychain item unavailable');
    assert.equal(source.stdout.toString('utf8').replace(/\n$/, ''), secret);
    const bytes = safeStorage.encryptString(secret);
    assert.ok(!bytes.includes(Buffer.from(secret)));
    const path = join(directory, 'credentials.bin');
    await writeFile(path + '.partial', bytes, { mode: 0o600 });
    await rename(path + '.partial', path);
    assert.equal((await stat(path)).mode & 0o777, 0o600);
    assert.equal(safeStorage.decryptString(await readFile(path)), secret);
    const retained = await security(['find-generic-password', ...query, '-w']);
    assert.equal(retained.stdout.toString('utf8').replace(/\n$/, ''), secret);
    return 'synthetic Keychain source -> private atomic safeStorage file -> verified; source retained until test cleanup';
  } finally {
    const removed = await security(['delete-generic-password', ...query]);
    assert.ok(removed.code === 0 || removed.code === 44, 'Synthetic Keychain cleanup failed');
  }
}
