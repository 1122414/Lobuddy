import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import { copyFile, cp, mkdtemp, readFile, writeFile, chmod, rm } from 'node:fs/promises';
import { constants } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, '../../..');
const requireDesktop = createRequire(join(root, 'desktop/package.json'));
const positional = process.argv.slice(2).filter(arg => !['--relocate', '--crash'].includes(arg));
const binary = positional[0];
const vad = positional[1];
if (!binary || !vad) throw new Error('Usage: node dist/run.js ABSOLUTE_DSH_BINARY ABSOLUTE_SILERO_MODEL');
const temporary = await mkdtemp(join(tmpdir(), 'lobuddy-ts-qualification-'));
try {
  await copyFile(resolve(binary), join(temporary, 'dsh-runtime'));
  await chmod(join(temporary, 'dsh-runtime'), 0o700);
  await copyFile(resolve(vad), join(temporary, 'silero.onnx'));
  const policy = JSON.parse(await readFile(join(directory, '../runtime-policy.json'), 'utf8')) as { disabled: string[] };
  const relocate = process.argv.includes('--relocate');
  let main = join(directory, 'main.cjs');
  let plugin = join(root, 'bridge/dsh/dist/index.js');
  let model = positional[2] ? resolve(positional[2]) : undefined;
  if (relocate) {
    const target = join(temporary, 'app');
    const options = { recursive: true, mode: constants.COPYFILE_FICLONE };
    await cp(directory, join(target, 'dist'), options);
    await cp(join(directory, '../node_modules'), join(target, 'node_modules'), options);
    await copyFile(join(directory, '../package.json'), join(target, 'package.json'));
    await cp(join(root, 'bridge/dsh/dist'), join(target, 'plugin'), options);
    main = join(target, 'dist/main.cjs');
    plugin = join(target, 'plugin/index.js');
    if (model) {
      await cp(model, join(target, 'model'), options);
      model = join(target, 'model');
    }
  }
  await writeFile(join(temporary, 'config.json'), JSON.stringify({ ...policy,
    plugin, model,
    wave: positional[3] ? resolve(positional[3]) : undefined,
    manifest: join(directory, '../model-manifest.json'),
    corpus: positional[4] ? resolve(positional[4]) : undefined,
    corpusDirectory: positional[5] ? resolve(positional[5]) : undefined,
    corpusOutput: join(root, '.local-upgrade/ts-asr-results.json'),
    crash: process.argv.includes('--crash'),
  }), { mode: 0o600 });
  const executable = requireDesktop('electron') as string;
  await new Promise<void>((resolveDone, reject) => {
    const child = spawn(executable, [main], {
      env: { PATH: '/usr/bin:/bin', HOME: process.env.HOME, TMPDIR: temporary,
        LOBUDDY_QUALIFY_DIRECTORY: temporary }, stdio: ['ignore', 'inherit', 'inherit'],
    });
    const timeout = setTimeout(() => child.kill('SIGTERM'), 910_000);
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      clearTimeout(timeout);
      if (code === 0) resolveDone(); else reject(new Error(`Electron qualification exited ${code ?? signal}`));
    });
  });
  const report = JSON.parse(await readFile(join(temporary, 'result.json'), 'utf8')) as Record<string, unknown>;
  report.binarySha256 = createHash('sha256').update(await readFile(binary)).digest('hex');
  report.vadSha256 = createHash('sha256').update(await readFile(vad)).digest('hex');
  report.relocatedModulesAndModels = relocate;
  await writeFile(join(root, `.local-upgrade/ts-runtime${relocate ? '-relocated' : ''}${process.argv.includes('--crash') ? '-crash' : ''}-result.json`), JSON.stringify(report, null, 2) + '\n');
  console.log('PASS: isolated Electron/utilityProcess qualification. ASR/relocated application acceptance remains separate.');
} finally { await rm(temporary, { recursive: true, force: true }); }
