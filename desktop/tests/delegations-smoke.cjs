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
  try {
    app = await launch(); let page = await app.firstWindow();
    await page.waitForURL(/\/index\.html$/);
    await page.getByText('服务已连接', { exact: true }).waitFor();
    const call = (method, params, identity = crypto.randomUUID()) => page.evaluate(([method, params, identity]) => window.lobuddy.request(method, params, identity), [method, params, identity]);
    await call('learning.configure', { enabled: false });
    await page.getByRole('button', { name: '托付给她的事', exact: true }).click();
    await page.getByLabel('想托付的事').fill('跨会话归纳验收资料');
    await page.getByLabel('处理方式').selectOption('source-digest');
    await page.getByLabel('本次授权的文件或链接，每行一个').fill('note.txt');
    await page.getByRole('button', { name: '保存草稿', exact: true }).click();
    await page.getByRole('button', { name: '确认目标和范围', exact: true }).click();
    await page.getByRole('button', { name: '执行一次', exact: true }).click();
    await page.getByText('已完成', { exact: true }).waitFor();
    let list = await call('delegation.list', {});
    assert.equal(list.length, 1);
    const id = list[0].id;
    const detail = await call('delegation.get', { delegation_id: id });
    assert.equal(detail.runs.length, 1); assert.equal(detail.runs[0].verdict, 'verified');
    await page.reload();
    await page.getByRole('button', { name: '托付给她的事', exact: true }).click();
    await page.getByText('跨会话归纳验收资料', { exact: true }).waitFor();
    assert.equal((await call('delegation.list', {})).length, 1);
    const draft = { goal: '稍后继续看项目', kind: 'reminder', criteria: ['通知按规则投递（不代表已读）'], wait: { kind: 'time', at: Date.now() / 1000 + 3600, timezone: 'Asia/Shanghai' } };
    const first = await call('delegation.create', draft, 'stable-reminder');
    assert.equal((await call('delegation.create', draft, 'stable-reminder')).id, first.id);
    await call('delegation.confirm', { delegation_id: first.id, revision: 1, expires_at: Date.now() / 1000 + 7200 });
    await call('delegation.pause', { delegation_id: first.id, revision: 2 });
    await app.close(); app = await launch(); page = await app.firstWindow();
    await page.waitForURL(/\/index\.html$/);
    await page.getByText('服务已连接', { exact: true }).waitFor();
    list = await call('delegation.list', {});
    assert.equal(list.length, 2);
    assert.equal(list.find(item => item.id === first.id).status, 'paused');
    assert.equal(list.find(item => item.id === id).status, 'completed');
    await call('delegation.cancel', { delegation_id: first.id, revision: 3 });
    assert.equal((await call('delegation.get', { delegation_id: first.id })).delegation.status, 'cancelled');
    console.log('PASS: native creation/confirmation/execution/evidence, reload, durable dedup, restart and cancellation');
  } finally {
    if (app) await app.close();
    rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
