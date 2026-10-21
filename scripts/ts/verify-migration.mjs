import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';
import { resolve, relative, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const read = async path => JSON.parse(await readFile(resolve(root, path), 'utf8'));
const baseline = await read('migration/baseline/tests.json');
const progress = await read('migration/progress.json');
assert.equal(progress.baseline, '7195718');
const sources = new Set(baseline.map(test => test.source));
const reviewed = new Set();
const counts = { ported: 0, retired: 0, pending: 0 };
for (const item of progress.tests) {
  assert.ok(sources.has(item.source), `Unknown historical test: ${item.source}`);
  assert.ok(!reviewed.has(item.source), `Duplicate disposition: ${item.source}`);
  reviewed.add(item.source);
  assert.ok(['ported', 'retired'].includes(item.status), `Unsupported disposition: ${item.source}`);
  assert.match(item.stage, /^T(?:[0-9]|10)$/);
  assert.ok(typeof item.replacement === 'string' && item.replacement.trim(), `Missing replacement: ${item.source}`);
  if (item.status === 'retired') assert.ok(item.reason?.trim(), `Missing retirement rationale: ${item.source}`);
  const paths = [...item.replacement.matchAll(/(?:packages|desktop|qualification|scripts)\/[\w./-]+\.(?:ts|cts|cjs|mjs)/g)].map(match => match[0]);
  assert.ok(paths.length, `No concrete verification path: ${item.source}`);
  for (const path of paths) {
    const actual = resolve(root, path), local = relative(root, actual);
    assert.ok(!isAbsolute(local) && !local.startsWith('..'));
    await access(actual);
  }
  counts[item.status]++;
}
counts.pending = baseline.length - reviewed.size;
console.log(JSON.stringify({ baseline: progress.baseline, total: baseline.length, ...counts,
  status: counts.pending ? 'incomplete: Python retirement not approved by coverage ledger' : 'dispositions complete; test execution and product gates remain independent' }, null, 2));
// Normal checks permit incremental stages; the retirement gate must be explicit.
if (process.argv.includes('--complete')) assert.equal(counts.pending, 0, 'Historical assertions remain unresolved');
