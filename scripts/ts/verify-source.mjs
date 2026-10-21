import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../', import.meta.url));
const omitted = new Set(['node_modules','dist','dist-electron','release','__pycache__']);
async function inspect(directory) {
  for (const entry of await readdir(directory,{ withFileTypes: true })) {
    if (omitted.has(entry.name)) continue;
    const path = join(directory,entry.name);
    if (entry.isDirectory()) await inspect(path);
    else if (entry.isFile()) {
      assert.ok(!/\.(py|pyc|pyo|pyi)$/i.test(entry.name),`Retired source: ${path}`);
      if (path === fileURLToPath(import.meta.url)) continue;
      if (/\.(ts|cts|cjs|mjs|json|ya?ml)$/.test(entry.name)) {
        const source = await readFile(path,'utf8');
        assert.ok(!/(?:spawn(?:Sync)?|execFile(?:Sync)?)\s*\(\s*['"`](?:python\d?(?:\.\d+)?|pip\d?)['"`]/.test(source),`Retired executable: ${path}`);
        assert.ok(!/LOBUDDY_PYTHON|setup-python|python\s+-m\s+(?:pip|app\.)/.test(source),`Retired default path: ${path}`);
      }
    }
  }
}
for (const entry of await readdir(root,{ withFileTypes: true })) if (entry.isFile()) {
  assert.ok(!/\.(py|pyi)$/.test(entry.name),`Retired root source: ${entry.name}`);
}
for (const directory of ['packages','desktop','bridge','qualification','scripts','.github']) await inspect(resolve(root,directory));
for (const file of ['package.json','desktop/package.json','bridge/dsh/package.json','qualification/ts-runtime/package.json']) {
  const json = JSON.parse(await readFile(resolve(root,file),'utf8'));
  assert.ok(!/python|pip |PySide|nanobot/i.test(JSON.stringify(json.scripts ?? {})),`Retired package command: ${file}`);
}
console.log('Default source, runtime entries and CI use Node/TypeScript; historical records and private local caches are excluded.');
