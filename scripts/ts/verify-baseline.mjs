import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';

const root = new URL('../../', import.meta.url);
const directory = new URL('migration/baseline/', root);
const read = async (name) => JSON.parse(await readFile(new URL(name, directory), 'utf8'));
const manifest = await read('manifest.json');
for (const [name, digest] of Object.entries(manifest.files)) {
  assert.match(name, /^[a-z]+\.json$/);
  const actual = createHash('sha256').update(await readFile(new URL(name, directory))).digest('hex');
  assert.equal(actual, digest, `${name}: frozen baseline changed`);
}
const methods = await read('methods.json');
const tests = await read('tests.json');
const cases = await read('cases.json');
const schemas = await read('schemas.json');
const validators = await read('validators.json');
const database = await read('database.json');
assert.equal(manifest.baseline, '7195718');
assert.equal(methods.length, 110);
assert.equal(tests.length, 1077);
assert.equal(manifest.methods, methods.length);
assert.equal(manifest.tests, tests.length);
assert.equal(manifest.cases, cases.length);
assert.equal(manifest.schemas, Object.keys(schemas).length);
assert.equal(manifest.validators, validators.length);
assert.equal(new Set(methods.map((item) => item.method)).size, methods.length);
assert.equal(new Set(tests.map((item) => item.source)).size, tests.length);
assert.equal(new Set(cases.map((item) => item.id)).size, cases.length);
const names = new Set(methods.map((item) => item.method));
for (const item of methods) {
  assert.ok(schemas[item.parameters], `${item.method}: missing schema`);
  assert.ok(item.result_type, `${item.method}: missing result type`);
  assert.match(item.stage, /^T[3-8]$/);
  assert.ok(item.tests.length);
  assert.equal(cases.find((sample) => sample.id === `${item.method}:minimal`)?.accepted, true);
  assert.equal(cases.find((sample) => sample.id === `${item.method}:unknown`)?.accepted, false);
  assert.equal(cases.find((sample) => sample.id === `${item.method}:wrong-shape`)?.accepted, false);
}
for (const item of cases) assert.ok(names.has(item.method));
for (const item of tests) {
  assert.match(item.stage, /^T[3-8]$/);
  assert.equal(item.status, 'pending');
  assert.equal(item.replacement, null);
  assert.ok(item.retirement_rule);
}
assert.equal(database.user_version, 2);
assert.ok(database.objects.length > 0);
assert.equal(new Set(database.objects.map((item) => `${item.type}:${item.name}`)).size, database.objects.length);
for (const item of database.objects) assert.ok(item.sql && item.tbl_name);
// Source paths are historical identifiers: T9 deliberately removes the old files.
console.log(JSON.stringify({ baseline: manifest.baseline, methods: methods.length,
  tests: tests.length, validationCases: cases.length, schemas: Object.keys(schemas).length,
  customValidators: validators.length, databaseObjects: database.objects.length,
  status: 'baseline integrity verified; TypeScript equivalence not yet verified' }, null, 2));
