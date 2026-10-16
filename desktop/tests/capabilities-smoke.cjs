// Real Electron/Python image, progress and settings acceptance with disposable records.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const { execFileSync } = require('node:child_process');
(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-p5-ui-'));
  const root = resolve(__dirname, '../..');
  const source = join(temporary, 'red.png');
  execFileSync(join(root, '.venv/bin/python'), ['-c', 'from PIL import Image; import sys; Image.new("RGB",(80,80),"red").save(sys.argv[1])', source]);
  const application = await electron.launch({ args: [resolve(__dirname, '..')], env: { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace') }, timeout: 30000 });
  const errors = [];
  try {
    const page = await application.firstWindow();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await application.evaluate(({ BrowserWindow, dialog }, path) => {
      BrowserWindow.getAllWindows()[0].setSize(1536, 1024);
      // Choose a synthetic file in the main process; no file path is supplied by renderer IPC.
      dialog.showOpenDialog = async () => ({ canceled: false, filePaths: [path] });
    }, source);
    const blocked = await page.evaluate(async () => {
      try { await window.lobuddy.request('image.import', { path: '/etc/passwd' }, crypto.randomUUID()); return false; } catch { return true; }
    });
    assert.equal(blocked, true);
    await page.getByRole('button', { name: '添加图片', exact: true }).click();
    await page.getByAltText('待发送图片').waitFor();
    await page.getByLabel('消息', { exact: true }).fill('图片是什么颜色？只回答颜色。');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.waitForFunction(async () => (await window.lobuddy.request('task.list', {}, crypto.randomUUID())).some(task => task.status === 'completed'), null, { timeout: 150000 });
    await page.getByAltText('已发送图片').waitFor();
    await page.screenshot({ path: '/tmp/lobuddy-p5-image.png' });
    await page.getByRole('button', { name: '成长', exact: true }).click();
    await page.getByText('一起积累的日常', { exact: true }).waitFor();
    await page.getByText('5 EXP · 阶段 1', { exact: true }).waitFor();
    await page.screenshot({ path: '/tmp/lobuddy-p5-progress.png' });
    console.log('PASS: native image picker, rejected direct path IPC, real model, image history and growth page');
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByLabel('伙伴的名字', { exact: true }).fill('小蒂');
    await page.getByLabel('每轮最多工具调用', { exact: true }).fill('4');
    await page.getByRole('button', { name: '保存设置', exact: true }).click();
    await page.getByText('设置已保存，重新启动后生效。', { exact: true }).waitFor();
    const config = await page.evaluate(() => window.lobuddy.request('settings.get', {}, crypto.randomUUID()));
    assert.equal(config.values.pet_name, '小蒂');
    assert.equal(config.values.execution_max_tool_calls_per_task, 4);
    assert.equal('llm_api_key' in config.values, false);
    assert.equal(config.credentials.llm_api_key, true);
    await page.screenshot({ path: '/tmp/lobuddy-p5-settings.png' });
    await page.reload();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    assert.equal(await page.getByLabel('伙伴的名字', { exact: true }).inputValue(), '小蒂');
    assert.deepEqual(errors, []);
    console.log('PASS: validated settings, opaque credential status, saved settings after renderer reload and no page errors');
  } finally { await application.close(); rmSync(temporary, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
