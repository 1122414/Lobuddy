import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { pcm16Mono } from './speech-probe.js';

export async function qualifyCorpus(model: string, directory: string, manifestPath: string, output: string) {
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8')) as {
    cases: { id: string; file: string; text: string; sha256: string }[];
  };
  assert.ok(manifest.cases.length >= 100);
  const { env, pipeline } = await import('@huggingface/transformers');
  env.allowRemoteModels = false;
  const asr = await pipeline('automatic-speech-recognition', model, {
    device: 'cpu', dtype: 'q8', local_files_only: true,
    session_options: { intraOpNumThreads: 4, interOpNumThreads: 1 },
  });
  const options = { language: 'chinese', task: 'transcribe', num_beams: 1, do_sample: false };
  const results: { id: string; text: string; ms: number }[] = [];
  try {
    await asr(pcm16Mono(await readFile(join(directory, manifest.cases[0]!.file))), options);
    for (const item of manifest.cases) {
      assert.match(item.file, /^[a-z0-9_-]+\.wav$/);
      const bytes = await readFile(join(directory, item.file));
      assert.equal(createHash('sha256').update(bytes).digest('hex'), item.sha256);
      const audio = pcm16Mono(bytes);
      const start = performance.now();
      const result = await asr(audio, options);
      results.push({ id: item.id, text: result.text, ms: performance.now() - start });
      if (results.length % 20 === 0) console.error(`ASR corpus: ${results.length}/${manifest.cases.length}`);
    }
  } finally { await asr.dispose(); }
  await writeFile(output, JSON.stringify({ engine: 'whisper-small-onnx-q8',
    node: process.versions.node, electron: process.versions.electron,
    threads: 4, corpusSha256: createHash('sha256').update(await readFile(manifestPath)).digest('hex'),
    results }, null, 2) + '\n');
  return { clips: results.length, status: 'completed; compare with sequential legacy benchmark before acceptance' };
}
