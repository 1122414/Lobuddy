const { test } = require('node:test');
const assert = require('node:assert/strict');
const { waitFor } = require('./wait-for.cjs');
test('business polling awaits async false values instead of accepting the Promise', async () => {
  let calls = 0;
  const page = { evaluate: async predicate => predicate() };
  await waitFor(page, async () => ++calls >= 3);
  assert.equal(calls, 3);
  await assert.rejects(waitFor(page, async () => false, null, { timeout: 120 }), /timeout/);
});
