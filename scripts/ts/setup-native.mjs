import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
const desktopRequire = createRequire(new URL('../../desktop/package.json', import.meta.url));
const manifest = desktopRequire.resolve('electron/package.json');
const metadata = JSON.parse(await readFile(manifest, 'utf8'));
if (metadata.version !== '44.8.0') throw new Error('Electron differs from the qualified version');
// Only Electron's reviewed, checksummed binary downloader runs. npm lifecycle hooks stay disabled.
const installer = join(dirname(manifest), 'install.js');
await new Promise((done, reject) => {
  const child = spawn(process.execPath, [installer], { cwd: fileURLToPath(new URL('../..', import.meta.url)),
    env: { PATH: process.env.PATH, HOME: process.env.HOME, TMPDIR: process.env.TMPDIR }, stdio: 'inherit' });
  child.once('error', reject);
  child.once('exit', code => code === 0 ? done() : reject(new Error(`Electron binary setup exited ${code}`)));
});
