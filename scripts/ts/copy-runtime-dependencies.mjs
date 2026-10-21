// Preserve Node's resolved dependency graph without relying on workspace hoisting.
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { access, cp, mkdir, readFile, realpath, symlink, readlink } from 'node:fs/promises';
import { dirname, join, relative, resolve } from 'node:path';
const [manifest, packageName, output] = process.argv.slice(2);
if (!manifest || !packageName || !output) throw new Error('Expected MANIFEST PACKAGE OUTPUT');
const modules = resolve(output);
const copied = new Map();
async function locate(name, from) {
  if (!/^(@[a-z0-9_.-]+\/)?[a-z0-9_.-]+$/i.test(name)) throw new Error('Invalid package name');
  for (const directory of createRequire(from).resolve.paths(name) ?? []) {
    const candidate = join(directory, name, 'package.json');
    try { await access(candidate); return await realpath(candidate); } catch { /* Continue Node lookup. */ }
  }
  throw new Error(`Missing runtime dependency: ${name}`);
}
async function link(target, path) {
  await mkdir(dirname(path), { recursive: true });
  const destination = relative(dirname(path), target);
  try { await symlink(destination, path, 'dir'); }
  catch (error) {
    if (error.code !== 'EEXIST' || await readlink(path) !== destination) throw error;
  }
}
async function copy(source) {
  if (copied.has(source)) return copied.get(source);
  if (copied.size >= 1000) throw new Error('Runtime dependency closure exceeds bound');
  const metadata = JSON.parse(await readFile(source, 'utf8'));
  // Installed location distinguishes equal versions with different peer resolutions.
  const lockRoot = resolve(manifest, '..');
  const identity = createHash('sha256').update(relative(lockRoot, source)).digest('hex').slice(0, 24);
  const target = join(modules, '.lobuddy-runtime', identity);
  copied.set(source, target);
  await mkdir(dirname(target), { recursive: true });
  await cp(dirname(source), target, { recursive: true,
    filter: path => path !== join(dirname(source), 'node_modules') });
  const dependencies = { ...metadata.dependencies, ...metadata.peerDependencies, ...metadata.optionalDependencies };
  for (const dependency of Object.keys(dependencies)) {
    const optional = Object.hasOwn(metadata.optionalDependencies ?? {}, dependency) || metadata.peerDependenciesMeta?.[dependency]?.optional;
    let resolved;
    try { resolved = await locate(dependency, source); }
    catch (error) { if (optional) continue; throw error; }
    await link(await copy(resolved), join(target, 'node_modules', dependency));
  }
  return target;
}
for (const name of packageName.split(',')) {
  await link(await copy(await locate(name, resolve(manifest))), join(modules, name));
}
console.log(`Copied ${copied.size} distinct runtime packages from the installed lock.`);
