// Real Electron + Python + DSH smoke; temporary workspace only. Requires configured .env.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, existsSync, readFileSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-desktop-'));
  const desktop = resolve(__dirname, '..');
  const args = process.env.LOBUDDY_PACKAGE ? [] : [desktop];
  const application = await electron.launch({ args, executablePath: process.env.LOBUDDY_PACKAGE || undefined, env: { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace') }, timeout: 30000 });
  application.process().stderr.on('data', chunk => { const match = /Business task failed: [A-Za-z]+/.exec(chunk.toString()); if (match) console.log(match[0]); });
  try {
    let page = await application.firstWindow();
    page.setDefaultTimeout(30000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => typeof window.require), 'undefined');
    assert.equal(await page.evaluate(() => typeof window.process), 'undefined');
    const preferences = await application.evaluate(({ BrowserWindow }) => { const p = BrowserWindow.getAllWindows().find(window => window.webContents.getURL() === 'lobuddy://app/index.html').webContents.getLastWebPreferences(); return { sandbox: p.sandbox, isolation: p.contextIsolation, node: p.nodeIntegration }; });
    assert.deepEqual(preferences, { sandbox: true, isolation: true, node: false });
    await page.getByRole('button', { name: '新对话', exact: true }).click();
    await page.locator('.session-list button').waitFor();
    const send = async text => {
      await page.getByRole('textbox', { name: '消息', exact: true }).fill(text);
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await page.waitForFunction(async text => (await window.lobuddy.request('task.list', {}, crypto.randomUUID()))[0]?.input_text === text, text);
    };
    const terminal = async status => {
      await page.waitForFunction(async status => (await window.lobuddy.request('task.list', {}, crypto.randomUUID()))[0]?.status === status, status, { timeout: 90000 });
      await page.locator('.task-row[data-status="running"]').waitFor({ state: 'detached' });
    };
    await send('请只回复“你好呀”。');
    await page.locator('.message.assistant .message-content').waitFor({ timeout: 90000 }).catch(async error => {
      console.log(await page.locator('body').innerText());
      console.log(await page.evaluate(() => window.lobuddy.request('task.list', {}, crypto.randomUUID())));
      await page.screenshot({ path: '/tmp/lobuddy-p3-failure.png' });
      throw error;
    });
    await terminal('completed');
    assert.equal(await page.locator('.message.user').count(), 1);
    await page.reload();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.locator('.message.assistant .message-content').waitFor();
    assert.equal(await page.locator('.message.user').count(), 1);
    console.log('PASS: isolated Electron renderer, real model, persisted history after reload');
    await send('请调用 lobuddy_write_file 写入 acceptance.txt，内容 hello。若拒绝，就停止，不要重试。');
    await page.getByRole('dialog').waitFor({ timeout: 90000 });
    await page.evaluate(() => window.lobuddy.windowAction('chat'));
    await page.waitForTimeout(500);
    const quick = application.windows().find(window => window.url().includes('surface=quick'));
    assert.ok(quick);
    await quick.getByRole('dialog').waitFor();
    assert.equal(await page.evaluate(async () => (await window.lobuddy.request('approval.list', {}, crypto.randomUUID())).length), 1);
    await quick.getByRole('button', { name: '拒绝', exact: true }).click();
    await quick.getByRole('button', { name: '关闭快速聊天' }).click();
    await terminal('completed');
    assert.equal(existsSync(join(temporary, 'workspace/acceptance.txt')), false);
    await send('现在我明确允许本次写入。请调用 lobuddy_write_file 写入 acceptance.txt，内容 hello；若拒绝，就停止。');
    await page.getByRole('dialog').waitFor({ timeout: 90000 });
    await page.screenshot({ path: '/tmp/lobuddy-p3-approval.png' });
    await page.getByRole('button', { name: '允许本次', exact: true }).click();
    // File existence plus the next terminal visible state prove the actual effect, not only a UI label.
    await terminal('completed');
    assert.equal(readFileSync(join(temporary, 'workspace/acceptance.txt'), 'utf8').trim(), 'hello');
    console.log('PASS: real approval rejection and explicit allowance');
    await send('请调用 lobuddy_write_file 写入 close-denied.txt，内容 test；若拒绝，就停止。');
    await page.getByRole('dialog').waitFor({ timeout: 90000 });
    await page.reload();
    await terminal('completed');
    assert.equal(existsSync(join(temporary, 'workspace/close-denied.txt')), false);
    console.log('PASS: refresh while awaiting approval denies the effect');
    await send('请写一篇很长的关于海洋的文章。');
    await page.locator('.message:has(.task-row[data-status="running"]) .message-content').waitFor({ timeout: 90000 });
    await page.getByRole('button', { name: '取消', exact: true }).waitFor({ timeout: 90000 });
    await page.getByRole('button', { name: '取消', exact: true }).click();
    await page.getByText('已取消', { exact: true }).waitFor({ timeout: 90000 });
    console.log('PASS: cancellation is visible as cancelled');
    await page.getByRole('button', { name: '任务', exact: true }).click();
    await page.getByRole('region', { name: '任务列表' }).waitFor();
    assert.equal(await page.locator('.task-list .task-row').count(), 5);
    await page.getByRole('button', { name: '对话', exact: true }).click();
    const nextWindow = application.waitForEvent('window');
    await application.evaluate(({ BrowserWindow, app }) => { const window = BrowserWindow.getAllWindows().find(window => window.webContents.getURL() === 'lobuddy://app/index.html'); window.once('closed', () => app.emit('activate')); window.close(); });
    page = await nextWindow;
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.locator('.message.user').first().waitFor();
    assert.equal(await page.locator('.message.user').count(), 5);
    console.log('PASS: actual window close/reopen preserves five distinct submissions');
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(window => window.webContents.getURL() === 'lobuddy://app/index.html').setSize(1536, 1024));
    await page.screenshot({ path: '/tmp/lobuddy-p3-desktop.png' });
    assert.deepEqual(errors, []);
    console.log('PASS: task navigation and renderer error check');
  } catch (error) {
    const page = application.windows().find(window => !window.isClosed());
    if (page) {
      console.log(await page.evaluate(() => window.lobuddy.request('task.list', {}, crypto.randomUUID())));
      await page.screenshot({ path: '/tmp/lobuddy-p3-failure.png' });
    }
    throw error;
  } finally {
    await application.close();
    rmSync(temporary, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
