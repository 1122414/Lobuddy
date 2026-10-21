import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile, rename, chmod } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { unzipSync } from 'fflate';

type Asset = { url: string; size: number; sha256: string };
const base = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const destination = resolve(process.argv[2] ?? '.local-upgrade/ts-assets');
await mkdir(destination, { recursive: true, mode: 0o700 });
async function obtain(asset: Asset): Promise<Buffer> {
  assert.match(asset.sha256, /^[a-f0-9]{64}$/);
  const response = await fetch(asset.url, { signal: AbortSignal.timeout(180_000) });
  assert.ok(response.ok, `Asset download returned ${response.status}`);
  const reader = response.body!.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const packet = await reader.read();
      if (packet.done) break;
      size += packet.value.byteLength;
      assert.ok(size <= asset.size, 'Asset exceeds pinned size');
      chunks.push(packet.value);
    }
  } finally { await reader.cancel(); }
  const bytes = Buffer.concat(chunks);
  assert.equal(bytes.length, asset.size);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), asset.sha256);
  return bytes;
}
async function atomic(path: string, bytes: Uint8Array, mode = 0o600) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path + '.partial', bytes, { mode });
  await chmod(path + '.partial', mode);
  await rename(path + '.partial', path);
}
const native = JSON.parse(await readFile(join(base, 'native-manifest.json'), 'utf8')) as {
  dsh: Asset & { entry: string; runtimeSize: number; runtimeSha256: string }; vad: Asset;
};
const archive = await obtain(native.dsh);
const entries = unzipSync(archive, { filter: (entry) => {
  const wanted = entry.name === native.dsh.entry || /\.dist-info\/licenses\//.test(entry.name);
  if (entry.name === native.dsh.entry) assert.equal(entry.originalSize, native.dsh.runtimeSize);
  else if (wanted) assert.ok(entry.originalSize <= 10_000_000);
  return wanted;
} });
assert.ok(entries[native.dsh.entry], 'Official distribution lacks the expected runtime');
assert.equal(createHash('sha256').update(entries[native.dsh.entry]!).digest('hex'), native.dsh.runtimeSha256);
await atomic(join(destination, 'dsh-runtime'), entries[native.dsh.entry]!, 0o700);
const licenseFiles = Object.keys(entries).filter(name => name !== native.dsh.entry);
assert.ok(licenseFiles.length > 0, 'Official distribution licenses missing');
for (const [index, name] of licenseFiles.entries()) {
  await atomic(join(destination, 'licenses', `dsh-${index}.txt`), entries[name]!);
}
await atomic(join(destination, 'silero.onnx'), await obtain(native.vad));
const model = JSON.parse(await readFile(join(base, 'model-manifest.json'), 'utf8')) as {
  files: (Asset & { name: string })[];
};
for (const file of model.files) {
  assert.match(file.name, /^(onnx\/)?[a-z_]+\.(json|onnx)$/);
  await atomic(join(destination, 'whisper-small', file.name), await obtain(file));
  console.log(`Verified ${file.name}`);
}
await atomic(join(destination, 'provenance.json'), Buffer.from(JSON.stringify({ native, model,
  extractedLicenseFiles: licenseFiles,
  runtimeSha256: createHash('sha256').update(entries[native.dsh.entry]!).digest('hex'),
}, null, 2)));
console.log('Verified standalone runtime, VAD and Whisper assets without Python.');
