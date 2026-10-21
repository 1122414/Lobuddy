const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { _electron: electron } = require('playwright');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-e3-ui-'));
  let app;
  try {
    await (await import('./fixtures.mjs')).seedFixture('outcomes',temp);
    const bootstrap = join(temp, 'start.cjs');
    writeFileSync(bootstrap, `const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temp, 'electron'))});app.setAppPath(${JSON.stringify(join(root, 'desktop'))});require(${JSON.stringify(join(root, 'desktop/dist-electron/desktop/electron/main.js'))});`);
    app = await electron.launch({ args: [bootstrap], env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace') } });
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '任务', exact: true }).click();
    await page.getByText('执行结束', {exact: true}).waitFor();
    await page.getByText('结果已验证', {exact: true}).click();
    await page.getByText('副本数量与 SHA-256 一致', {exact: true}).waitFor();
    await page.getByText('已验证1份测试副本', {exact: true}).waitFor();
    console.log('PASS E3 UI: execution status separated from result, criteria and evidence visible');
  } finally { if (app) await app.close(); rmSync(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
