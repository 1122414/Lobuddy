import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, rename } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute = promisify(execFile);
test('runtime copy preserves shared dependencies, cycles and nested versions after relocation', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'lobuddy-copy-test-'));
  const source = join(temporary, 'source');
  const target = join(temporary, 'target');
  const relocated = join(temporary, 'relocated');
  const make = async (path, metadata, code) => {
    await mkdir(path, { recursive: true });
    await writeFile(join(path, 'package.json'), JSON.stringify({ version: '1.0.0', main: 'index.cjs', ...metadata }));
    await writeFile(join(path, 'index.cjs'), code);
  };
  try {
    await make(source, { name: 'fixture' }, '');
    await make(join(source, 'node_modules/a'), { name: 'a', dependencies: { b: '*', c: '*' },
      optionalDependencies: { absent: '*' } }, 'exports.result=()=>[require("b").version,require("c"),require("b").cycle()];');
    await make(join(source, 'node_modules/b'), { name: 'b', dependencies: { a: '*' } },
      'exports.version=1; exports.cycle=()=>typeof require("a").result;');
    await make(join(source, 'node_modules/c'), { name: 'c', dependencies: { b: '*' } }, 'module.exports=require("b").version;');
    await make(join(source, 'node_modules/c/node_modules/b'), { name: 'b', version: '2.0.0' }, 'exports.version=2;');
    const copied = await execute(process.execPath, [fileURLToPath(new URL('./copy-runtime-dependencies.mjs', import.meta.url)),
      join(source, 'package.json'), 'a,c', join(target, 'node_modules')]);
    assert.match(copied.stdout, /Copied 4 distinct/);
    await writeFile(join(target, 'probe.cjs'), 'console.log(JSON.stringify([require("a").result(),require("c")]));');
    await rename(target, relocated);
    await rm(source, { recursive: true });
    const result = await execute(process.execPath, [join(relocated, 'probe.cjs')], { cwd: relocated });
    assert.deepEqual(JSON.parse(result.stdout), [[1, 2, 'function'],2]);
  } finally { await rm(temporary, { recursive: true, force: true }); }
});
