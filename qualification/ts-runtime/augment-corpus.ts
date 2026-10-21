import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { pcm16Mono } from './speech-probe.js';

const directory = resolve(process.argv[2] ?? '.local-upgrade/ts-corpus');
const manifestPath = resolve(process.argv[3] ?? 'qualification/ts-runtime/corpus-manifest.json');
type Sample = { id: string; file: string; sha256: string; text: string; source: string;
  license: string; tags: string[]; seconds: number; derivedFrom?: string; transformation?: string };
const manifest = JSON.parse(await readFile(manifestPath, 'utf8')) as { cases: Sample[]; limitations: string[] };
manifest.cases = manifest.cases.filter(item => !item.derivedFrom);
assert.equal(manifest.cases.length, 108);
function wav(samples: Float32Array): Buffer {
  const out = Buffer.alloc(44 + samples.length * 2);
  out.write('RIFF'); out.writeUInt32LE(out.length - 8, 4); out.write('WAVEfmt ', 8);
  out.writeUInt32LE(16, 16); out.writeUInt16LE(1, 20); out.writeUInt16LE(1, 22);
  out.writeUInt32LE(16_000, 24); out.writeUInt32LE(32_000, 28);
  out.writeUInt16LE(2, 32); out.writeUInt16LE(16, 34); out.write('data', 36);
  out.writeUInt32LE(samples.length * 2, 40);
  for (let i = 0; i < samples.length; i++) out.writeInt16LE(Math.max(-32768, Math.min(32767, Math.round(samples[i]! * 32768))), 44 + i * 2);
  return out;
}
for (const id of ['cmn_hans_cn_0000', 'cmn_hans_cn_0002', 'cmn_hans_cn_0003', 'taiwan-0', 'taiwan-1', 'taiwan-2']) {
  const source = manifest.cases.find(item => item.id === id)!;
  assert.ok(source);
  const bytes = await readFile(join(directory, source.file));
  assert.equal(createHash('sha256').update(bytes).digest('hex'), source.sha256);
  const audio = pcm16Mono(bytes);
  for (const kind of ['noise', 'pause'] as const) {
    let altered: Float32Array;
    if (kind === 'pause') {
      altered = new Float32Array(audio.length + 11_200);
      const midpoint = Math.floor(audio.length / 2);
      altered.set(audio.subarray(0, midpoint)); altered.set(audio.subarray(midpoint), midpoint + 11_200);
    } else {
      const rms = Math.sqrt(audio.reduce((sum, x) => sum + x * x, 0) / audio.length);
      const amplitude = rms / Math.pow(10, 15 / 20) * Math.sqrt(3);
      let state = 0x4c6f6275;
      altered = Float32Array.from(audio, sample => {
        state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
        return sample + ((state >>> 0) / 0xffffffff * 2 - 1) * amplitude;
      });
    }
    const result = wav(altered);
    const variant = `${id}-${kind}`;
    await writeFile(join(directory, `${variant}.wav`), result);
    manifest.cases.push({ ...source, id: variant, file: `${variant}.wav`,
      seconds: altered.length / 16_000, sha256: createHash('sha256').update(result).digest('hex'),
      tags: [...source.tags, kind], derivedFrom: id,
      transformation: kind === 'pause' ? 'Insert 700 ms zero PCM at midpoint; preserve reference.'
        : 'Seed 0x4c6f6275 xorshift32 uniform noise, target 15 dB SNR before PCM clipping; preserve reference.' });
  }
}
manifest.limitations = ['Taiwan source has no speaker demographics; provenance is not accent certification.',
  '12 deterministic noise/pause derivatives augment 108 independent source clips; not natural noisy recordings.',
  'CER normalizes NFKC/case/punctuation/whitespace equally; no model-specific corrections or script conversion.'];
await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n');
console.log('Frozen 120 clips: 108 source + 12 controlled noise/pause variants.');
