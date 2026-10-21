import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { pcm16Mono } from './speech-probe.js';

test('CER and P95 thresholds reject real regressions and mismatched corpus', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'lobuddy-metrics-'));
  try {
    const cases = Array.from({ length: 100 }, (_, index) => ({ id: String(index), text: '甲'.repeat(100), tags: [] }));
    const bytes = Buffer.from(JSON.stringify({ cases }));
    const digest = createHash('sha256').update(bytes).digest('hex');
    await writeFile(join(directory, 'manifest.json'), bytes);
    const results = (errors: number, ms: number) => ({ corpusSha256: digest,
      results: cases.map(item => ({ id: item.id, text: '甲'.repeat(100 - errors) + '乙'.repeat(errors), ms })) });
    await writeFile(join(directory, 'old.json'), JSON.stringify(results(0, 100)));
    const run = async (current: unknown) => {
      await writeFile(join(directory, 'new.json'), JSON.stringify(current));
      return spawnSync(process.execPath, [join(dirname(fileURLToPath(import.meta.url)), 'compare-corpus.js'),
        ...['manifest.json', 'new.json', 'old.json', 'report.json'].map(name => join(directory, name))], { encoding: 'utf8' });
    };
    assert.equal((await run(results(2, 120))).status, 0);
    const report = JSON.parse(await readFile(join(directory, 'report.json'), 'utf8'));
    assert.equal(report.cerDifferencePercentagePoints, 2);
    assert.equal(report.warmP95Ratio, 1.2);
    assert.equal((await run(results(3, 120))).status, 1);
    assert.equal((await run(results(2, 121))).status, 1);
    assert.equal((await run({ ...results(0, 100), corpusSha256: 'incorrect' })).status, 1);
    assert.equal((await run({ ...results(0, 100), results: results(0, 100).results.slice(1) })).status, 1);
  } finally { await rm(directory, { recursive: true, force: true }); }
});

test('audio probe rejects unsupported sample format and truncated containers', () => {
  const bytes = Buffer.alloc(48);
  bytes.write('RIFF'); bytes.writeUInt32LE(40, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22);
  bytes.writeUInt32LE(16_000, 24); bytes.writeUInt32LE(32_000, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36);
  bytes.writeUInt32LE(4, 40); bytes.writeInt16LE(16384, 44); bytes.writeInt16LE(-16384, 46);
  assert.deepEqual([...pcm16Mono(bytes)], [0.5, -0.5]);
  assert.throws(() => pcm16Mono(bytes.subarray(0, 47)));
  bytes.writeUInt32LE(48_000, 24);
  assert.throws(() => pcm16Mono(bytes));
});
