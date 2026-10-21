const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { _electron: electron } = require('playwright');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-e1-ui-'));
  let app;
  try {
    await (await import('./fixtures.mjs')).seedFixture('relationship',temp);
    const bootstrap = join(temp, 'start.cjs');
    writeFileSync(bootstrap, `const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temp, 'electron'))});app.setAppPath(${JSON.stringify(join(root, 'desktop'))});require(${JSON.stringify(join(root, 'desktop/dist-electron/desktop/electron/main.js'))});`);
    app = await electron.launch({ args: [bootstrap], env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace') } });
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '记忆', exact: true }).click();
    const panel = page.getByRole('region', { name: '她记住的我' });
    await panel.getByRole('button', { name: '请叫我小满。', exact: true }).click();
    await panel.getByLabel('修正相处记忆').fill('以后请叫我小雨。');
    await panel.getByRole('button', { name: '保存修正', exact: true }).click();
    await panel.getByRole('button', { name: '以后请叫我小雨。', exact: true }).click();
    await panel.getByText('来源消息', { exact: true }).click();
    await panel.getByText('请叫我小满。', { exact: false }).last().waitFor();
    await panel.getByLabel('同时删除 Lobuddy 中的来源聊天').check();
    await panel.getByRole('button', { name: '忘记这件事', exact: true }).click();
    await panel.getByText('还没有相处记忆。聊过的原文和已经记住的事情是分开的。', { exact: true }).waitFor();
    const history = await page.evaluate(() => window.lobuddy.request('session.history', { session_id: 'fixture' }, crypto.randomUUID()));
    assert.equal(history.length, 0);
    await panel.getByLabel('允许从相处中学习').uncheck();
    const policy = await page.evaluate(() => window.lobuddy.request('relationship.policy', {}, crypto.randomUUID()));
    assert.equal(policy.enabled, false);
    console.log('PASS E1: source-backed relation, correction, forget with source deletion, disable via real UI');
  } finally { if (app) await app.close(); rmSync(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
