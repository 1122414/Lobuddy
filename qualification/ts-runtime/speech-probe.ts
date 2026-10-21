import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join } from 'node:path';

export function pcm16Mono(bytes: Buffer): Float32Array {
  assert.equal(bytes.toString('ascii', 0, 4), 'RIFF');
  assert.equal(bytes.toString('ascii', 8, 12), 'WAVE');
  assert.equal(bytes.readUInt32LE(4) + 8, bytes.length);
  let format = false;
  let pcm: Buffer | undefined;
  for (let cursor = 12; cursor + 8 <= bytes.length;) {
    const name = bytes.toString('ascii', cursor, cursor + 4);
    const size = bytes.readUInt32LE(cursor + 4);
    const start = cursor + 8;
    assert.ok(start + size <= bytes.length);
    if (name === 'fmt ') {
      assert.ok(size >= 16);
      assert.equal(bytes.readUInt16LE(start), 1);
      assert.equal(bytes.readUInt16LE(start + 2), 1);
      assert.equal(bytes.readUInt32LE(start + 4), 16_000);
      assert.equal(bytes.readUInt16LE(start + 14), 16);
      format = true;
    }
    if (name === 'data') pcm = bytes.subarray(start, start + size);
    cursor = start + size + (size % 2);
  }
  assert.ok(format && pcm && pcm.length > 0 && pcm.length % 2 === 0);
  assert.ok(pcm.length <= 16_000 * 2 * 30, 'Qualification clips are bounded to 30 seconds');
  const audio = new Float32Array(pcm.length / 2);
  for (let index = 0; index < audio.length; index++) audio[index] = pcm.readInt16LE(index * 2) / 32768;
  return audio;
}

export async function qualifySpeech(model: string, wave: string, manifestPath: string) {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8')) as {
    revision: string; files: { name: string; sha256: string; size: number }[];
  };
  for (const file of manifest.files) {
    const bytes = await readFile(join(model, file.name));
    assert.equal(bytes.length, file.size);
    assert.equal(createHash('sha256').update(bytes).digest('hex'), file.sha256);
  }
  const audio = pcm16Mono(await readFile(wave));
  const { env, pipeline } = await import('@huggingface/transformers');
  env.allowRemoteModels = false;
  env.useBrowserCache = false;
  const loading = performance.now();
  const asr = await pipeline('automatic-speech-recognition', model, {
    device: 'cpu', dtype: 'q8', local_files_only: true,
    session_options: { intraOpNumThreads: 4, interOpNumThreads: 1 },
  });
  const loadMs = performance.now() - loading;
  const samples: { ms: number; characters: number }[] = [];
  try {
    for (let i = 0; i < 3; i++) {
      const started = performance.now();
      const result = await asr(audio, { language: 'chinese', task: 'transcribe',
        num_beams: 1, do_sample: false, max_new_tokens: 128 });
      assert.ok(result.text.trim().length > 0, 'Speech probe produced no text');
      samples.push({ ms: performance.now() - started, characters: [...result.text].length });
    }
  } finally { await asr.dispose(); }
  return { revision: manifest.revision, audioSeconds: audio.length / 16_000, loadMs, samples,
    status: 'single-clip load/transcription only; not corpus quality or P95 qualification' };
}
