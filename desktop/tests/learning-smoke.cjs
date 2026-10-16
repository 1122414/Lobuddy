// E0: real Electron → stdio → SQLite, synthetic data only; no model request.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync, writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');

(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-e0-'));
  let application;
  const bootstrap = join(temporary, 'bootstrap.cjs');
  writeFileSync(bootstrap, `const { app } = require('electron');
app.setPath('userData', ${JSON.stringify(join(temporary, 'electron'))});
app.setAppPath(${JSON.stringify(resolve(__dirname, '..'))});
require(${JSON.stringify(resolve(__dirname, '../dist-electron/desktop/electron/main.js'))});
`);
  const launch = () => electron.launch({ args: [bootstrap], env: {
    ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace'),
  }, timeout: 30000 });
  try {
    application = await launch();
    const page = await application.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    const panel = page.getByRole('region', { name: '后台学习' });
    await panel.getByText('等你空闲后处理', { exact: true }).waitFor();
    await panel.getByLabel('空闲多久开始（秒）').fill('1');
    await panel.getByRole('button', { name: '保存学习设置', exact: true }).click();
    let before;
    for (let i = 0; i < 60; i++) {
      before = await page.evaluate(() => window.lobuddy.request('learning.get', {}, crypto.randomUUID()));
      if (before.jobs.some(job => job.status === 'completed')) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.equal(before.jobs[0].status, 'completed');
    assert.equal(before.jobs[0].result.read_only, true);
    assert.equal(before.usage.calls, 0);
    await panel.getByLabel('允许后台学习').uncheck();
    await panel.getByRole('button', { name: '保存学习设置', exact: true }).click();
    await panel.getByText('已关闭', { exact: true }).waitFor();
    await application.close();
    application = await launch();
    const restored = await application.firstWindow();
    await restored.getByText('服务已连接', { exact: true }).waitFor();
    const after = await restored.evaluate(() => window.lobuddy.request('learning.get', {}, crypto.randomUUID()));
    assert.equal(after.policy.enabled, false);
    assert.equal(after.state, 'disabled');
    assert.equal(after.jobs[0].attempts, before.jobs[0].attempts);
    console.log('PASS E0: real settings, read-only maintenance, zero model calls, disabled restart and no replay');
  } finally {
    if (application) await application.close();
    rmSync(temporary, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
