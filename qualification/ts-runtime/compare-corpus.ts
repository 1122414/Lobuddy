import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const [manifestFile, currentFile, previousFile, outputFile] = process.argv.slice(2);
if (!manifestFile || !currentFile || !previousFile || !outputFile) throw new Error('Expected MANIFEST CURRENT PREVIOUS OUTPUT');
const manifestBytes = await readFile(manifestFile);
const manifest = JSON.parse(manifestBytes.toString()) as { cases: { id: string; text: string; tags: string[] }[] };
assert.ok(manifest.cases.length >= 100, 'Qualification requires at least 100 cases');
assert.equal(new Set(manifest.cases.map(item => item.id)).size, manifest.cases.length);
type Run = { corpusSha256: string; results: { id: string; text: string; ms: number }[] };
const current = JSON.parse(await readFile(currentFile, 'utf8')) as Run;
const previous = JSON.parse(await readFile(previousFile, 'utf8')) as Run;
const digest = createHash('sha256').update(manifestBytes).digest('hex');
const normalize = (text: string) => [...text.normalize('NFKC').toLowerCase().replace(/[\p{P}\p{Z}\p{S}\s]/gu, '')];
function distance(reference: string[], hypothesis: string[]): number {
  let row = Array.from({ length: hypothesis.length + 1 }, (_, i) => i);
  for (let i = 1; i <= reference.length; i++) {
    const next = [i];
    for (let j = 1; j <= hypothesis.length; j++) next[j] = Math.min(
      row[j]! + 1, next[j - 1]! + 1, row[j - 1]! + (reference[i - 1] === hypothesis[j - 1] ? 0 : 1));
    row = next;
  }
  return row[hypothesis.length]!;
}
function score(run: Run, tag?: string) {
  assert.equal(run.corpusSha256, digest);
  assert.equal(run.results.length, manifest.cases.length);
  const byId = new Map(run.results.map(item => [item.id, item]));
  assert.equal(byId.size, manifest.cases.length);
  let errors = 0, characters = 0;
  const times: number[] = [];
  for (const item of manifest.cases.filter(sample => !tag || sample.tags.includes(tag))) {
    const result = byId.get(item.id)!; assert.ok(result);
    assert.ok(Number.isFinite(result.ms) && result.ms > 0);
    const reference = normalize(item.text);
    errors += distance(reference, normalize(result.text)); characters += reference.length;
    times.push(result.ms);
  }
  times.sort((a, b) => a - b);
  return { clips: times.length, errors, characters, cer: errors / characters,
    warmP95Ms: times[Math.ceil(times.length * 0.95) - 1]! };
}
const before = score(previous), after = score(current);
const quality = after.cer - before.cer <= 0.02;
const speed = after.warmP95Ms <= before.warmP95Ms * 1.2;
const report = { corpusSha256: digest, previous: before, current: after,
  cerDifferencePercentagePoints: (after.cer - before.cer) * 100,
  warmP95Ratio: after.warmP95Ms / before.warmP95Ms,
  gates: { quality, speed },
  groups: Object.fromEntries(['mandarin', 'taiwan-source', 'numbers', 'mixed-language', 'noise', 'pause']
    .map(tag => [tag, { previous: score(previous, tag), current: score(current, tag) }])),
  status: quality && speed ? 'corpus gates passed; remaining T1/package/manual gates are separate' : 'T1 corpus gate failed',
};
await writeFile(outputFile, JSON.stringify(report, null, 2) + '\n');
console.log(JSON.stringify(report, null, 2));
if (!quality || !speed) process.exitCode = 1;
