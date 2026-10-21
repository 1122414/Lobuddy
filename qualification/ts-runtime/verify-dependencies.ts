import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const base = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const lock = JSON.parse(await readFile(join(base, '../../package-lock.json'), 'utf8')) as {
  packages: Record<string, { version: string; license?: string; integrity?: string }>;
};
const inventory = JSON.parse(await readFile(join(base, 'dependency-inventory.json'), 'utf8')) as {
  dependencies: { path: string; version: string; license: string; integrity: string | null }[];
};
for (const [path, dependency] of Object.entries(lock.packages)) {
  if (!path.includes('node_modules/') || !dependency.version) continue;
  const name = path.split('node_modules/').at(-1)!;
  if (name.startsWith('@deepseek-ai/dsh')) assert.equal(dependency.version, '0.1.5-rc.1', path);
  const entry = inventory.dependencies.find(item => item.path === path);
  assert.ok(entry, `${path}: license inventory missing`);
  assert.equal(entry.version, dependency.version);
  assert.equal(entry.license, dependency.license ?? 'unspecified');
  assert.equal(entry.integrity, dependency.integrity ?? null);
}
for (const [name, version] of Object.entries({ '@deepseek-ai/dsh-sdk-client': '0.1.5-rc.1',
  '@huggingface/transformers': '4.3.1', 'onnxruntime-node': '1.30.0', sharp: '0.35.5', fflate: '0.8.3' })) {
  const installed = Object.entries(lock.packages).filter(([path]) => path.endsWith(`node_modules/${name}`));
  assert.ok(installed.length > 0, name);
  for (const [, dependency] of installed) assert.equal(dependency.version, version);
}
console.log('PASS: exact DSH family and native inference dependencies; license inventory matches lock.');
