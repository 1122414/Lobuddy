const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, writeFileSync, rmSync } = require('node:fs');
const { join, resolve } = require('node:path');
const { tmpdir } = require('node:os');
const { bootstrapSource } = require('./runtime-evidence.cjs');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-delegations-'));
  mkdirSync(join(temp, 'workspace'));
  writeFileSync(join(temp, 'workspace/note.txt'), '决定：保留来源。\n待办：继续完善个人助手。');
  const bootstrap = join(temp, 'bootstrap.cjs');
  writeFileSync(bootstrap, bootstrapSource({ profile: join(temp, 'profile'), appPath: join(root, 'desktop'), mainPath: join(root, 'desktop/dist-electron/desktop/electron/main.js'), eventPath: join(temp, 'events.jsonl') }));
  const launch = () => electron.launch({ args: [bootstrap], env: { ...process.env, LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace'), LLM_API_KEY: 'synthetic-unused', LLM_MULTIMODAL_API_KEY: 'synthetic-unused', FISH_API_KEY: 'synthetic-unused' } });
  let app;
  const wait = async (check, label) => {
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) { if (await check()) return; await new Promise(resolve => setTimeout(resolve, 100)); }
    console.log('windows', await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().map(w => ({ url: w.webContents.getURL(), visible: w.isVisible() }))));
    for (const w of app.windows()) console.log('surface', await w.evaluate(async () => ({ hidden: document.hidden, surface: document.documentElement.dataset.surface, notices: await window.lobuddy.request('notification.list', {}, crypto.randomUUID()), policy: await window.lobuddy.request('companionship.get', {}, crypto.randomUUID()) })).catch(e => String(e)));
    throw Error('Timed out: ' + label);
  };
  try {
    app = await launch(); let page = await app.firstWindow();
    await page.waitForURL(/\/index\.html$/);
    await page.getByText('服务已连接', { exact: true }).waitFor();
    const call = (method, params, identity = crypto.randomUUID()) => page.evaluate(([method, params, identity]) => window.lobuddy.request(method, params, identity), [method, params, identity]);
    await call('learning.configure', { enabled: false });
    await call('companionship.configure', { do_not_disturb: true });
    await assert.rejects(call('notification.next', {}), /Only pet/);
    await assert.rejects(call('runtime.power', { suspended: true }), /native/);
    for (let i = 0; i < 2; i++) {
      const draft = await call('delegation.create', { goal: '原生提醒验收 ' + i, kind: 'reminder', criteria: ['通知按规则投递（不代表已读）'], wait: { kind: 'time', at: Date.now() / 1000 + 1, timezone: 'Asia/Shanghai' } });
      await call('delegation.confirm', { delegation_id: draft.id, revision: 1, expires_at: Date.now() / 1000 + 3600 });
    }
    await wait(async () => (await call('notification.list', {})).length === 2, 'durable pending reminders');
    assert.ok((await call('notification.list', {})).every(item => item.status === 'pending'));
    await app.evaluate(({ app, dialog }) => { globalThis.quitQuestions = []; dialog.showMessageBox = async options => { globalThis.quitQuestions.push(options); return { response: 1 }; }; app.quit(); });
    await wait(async () => await app.evaluate(() => globalThis.quitQuestions.length === 1), 'quit question');
    assert.equal(await app.evaluate(() => globalThis.quitQuestions[0].defaultId), 0);
    assert.match(await app.evaluate(() => globalThis.quitQuestions[0].message), /2/);
    assert.equal((await call('delegation.list', {})).length, 2);
    await app.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 0 }); });
    await app.close(); app = await launch(); page = await app.firstWindow();
    await page.waitForURL(/\/index\.html$/); await page.getByText('服务已连接', { exact: true }).waitFor();
    assert.equal((await call('notification.list', {})).length, 2);
    await page.getByRole('button', { name: '通知', exact: true }).click();
    await call('companionship.configure', { do_not_disturb: false });
    await wait(async () => (await call('notification.list', {})).every(item => item.status === 'delivered'), 'visible pet delivery');
    const notices = await call('notification.list', {});
    assert.equal(new Set(notices.map(item => item.batch_id)).size, 1);
    assert.ok(notices.every(item => item.read_at === null && item.delivered_at));
    await page.getByRole('button', { name: '通知', exact: true }).click();
    await page.getByRole('button', { name: '我看到了', exact: true }).first().click();
    await wait(async () => (await call('notification.list', {})).some(item => item.status === 'read'), 'explicit read');
    await wait(async () => (await call('delegation.list', {})).every(item => item.status === 'completed'), 'verified notification completion');
    await page.reload();
    assert.equal((await call('notification.list', {})).length, 2);
    console.log('PASS: native quiet inbox, merged visible delivery, explicit read, restart dedup, renderer ownership and quit-to-tray');
  } finally {
    if (app) { await app.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 0 }); }).catch(() => {}); await app.close(); }
    rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
