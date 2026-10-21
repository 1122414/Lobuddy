const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { _electron: electron } = require('playwright');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-e4-ui-'));
  let app;
  try {
    await (await import('./fixtures.mjs')).seedFixture('workflows',temp);
    const bootstrap = join(temp, 'start.cjs');
    writeFileSync(bootstrap, `const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temp, 'electron'))});app.setAppPath(${JSON.stringify(join(root, 'desktop'))});require(${JSON.stringify(join(root, 'desktop/dist-electron/desktop/electron/main.js'))});`);
    app = await electron.launch({ args: [bootstrap], env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace') } });
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '技能', exact: true }).click();
    const panel=page.getByRole('region',{name:'工作流与进化'});
    await panel.getByText('对话上下文 · probation · 当前使用',{exact:true}).click();
    await panel.getByRole('button',{name:'否定这次改变并回退'}).click();
    await panel.getByText('对话上下文 · rolled_back',{exact:true}).waitFor();
    await panel.getByText('运行受控办事场景',{exact:true}).click();
    await panel.getByLabel('整理输入目录').fill('input');
    await panel.getByLabel('整理输出目录').fill('output');
    await panel.getByRole('button',{name:'预览分类副本'}).click();
    await page.getByRole('dialog').waitFor();
    await page.getByRole('button',{name:'允许本次'}).click();
    await page.getByRole('button',{name:'任务',exact:true}).click();
    await page.getByText('结果已验证',{exact:true}).waitFor();
    console.log('PASS E4 UI: evidence/diff rollback and user-dispatched DAG copy with approval');
  } finally { if (app) await app.close(); rmSync(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
