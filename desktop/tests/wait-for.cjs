// Playwright waitForFunction treats a Promise as truthy before its result resolves.
// Business IPC predicates must be awaited in the test process on every attempt.
exports.waitFor = async function waitFor(page, predicate, arg = null, { timeout = 30000 } = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const result = await page.evaluate(predicate, arg);
    if (result) return result;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Business predicate did not become true before timeout');
};
