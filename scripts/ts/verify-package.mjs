import { lstat,readdir,readFile,writeFile,realpath } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { createHash } from 'node:crypto';
import { join,resolve,relative,sep } from 'node:path';
import assert from 'node:assert/strict';
const bundle=resolve(process.argv[2]??(await readFile('desktop/release/latest.txt','utf8')).trim());
const app=join(bundle,'Contents/Resources/app'),manifestPath=join(app,'assets/bundle-manifest.json');
const hash=async path=>{const digest=createHash('sha256');for await(const chunk of createReadStream(path))digest.update(chunk);return digest.digest('hex');};
const entries=[];
async function scan(directory){
  for(const name of (await readdir(directory)).sort()){
    const path=join(directory,name),key=relative(app,path).split(sep).join('/');
    if(path===manifestPath)continue;
    assert.ok(!/^(\.env(?:\..*)?|credentials\.json|lobuddy\.db(?:-.*)?|python(?:3(?:\.\d+)?)?)$/i.test(name),`Private/runtime file in bundle: ${key}`);
    assert.ok(!/\.(py|pyc|pyo)$/i.test(name),`Python file in bundle: ${key}`);
    const stat=await lstat(path);
    if(stat.isSymbolicLink()){
      const target=await realpath(path);assert.ok(target.startsWith(app+sep),`External link: ${key}`);
      entries.push({path:key,link:relative(app,target).split(sep).join('/')});
    }else if(stat.isDirectory())await scan(path);
    else {assert.ok(stat.isFile(),`Special file: ${key}`);entries.push({path:key,size:stat.size,sha256:await hash(path)});}
  }
}
await scan(app);
for(const path of ['dist/index.html','dist-electron/desktop/electron/main.js','packages/service/dist/utility-entry.cjs','packages/speech/dist/utility-entry.cjs','bridge/dsh/dist/index.js','assets/dsh-runtime']){
  const target=await realpath(join(app,path));assert.ok(target.startsWith(app+sep),`External runtime entry: ${path}`);
  assert.ok((await lstat(target)).isFile(),`Missing runtime entry: ${path}`);
}
const provenance=JSON.parse(await readFile(join(app,'assets/runtime-provenance.json'),'utf8'));
assert.equal(await hash(join(app,'assets/dsh-runtime')),provenance.runtimeSha256);
if(process.argv.includes('--write-manifest'))await writeFile(manifestPath,JSON.stringify({format:1,platform:'darwin-arm64',files:entries},null,2));
else assert.deepEqual(entries,JSON.parse(await readFile(manifestPath,'utf8')).files,'Bundle differs from its build manifest');
console.log(`Verified ${entries.length} bundle entries, internal dependency links and no Python/private data files.`);
