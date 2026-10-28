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
    const session = (await call('session.list', {}))[0] || await call('session.create', {});
    const turn = await call('turn.send', { session_id: session.id, text: '周五晚上提醒我继续看项目', workflow_id: 'source-digest', workflow_input: { sources: ['note.txt'] } });
    await page.getByRole('button', { name: '把这件事设为提醒', exact: true }).waitFor();
    await page.getByRole('button', { name: '把这件事设为提醒', exact: true }).click();
    await page.getByText('已保存待确认草稿。在“托付给她的事”选择具体时间后才会安排。', { exact: true }).waitFor();
    let list = await call('delegation.list', {});
    assert.equal(list.length, 1); assert.equal(list[0].status, 'draft');
    assert.equal(list[0].spec.source_message_id, turn.turn_id);
    assert.equal(list[0].spec.wait.kind, 'user');
    await assert.rejects(call('delegation.confirm', {delegation_id:list[0].id, revision:1, expires_at:Date.now()/1000+3600}));
    await page.getByRole('button', { name: '托付给她的事', exact: true }).click();
    await page.locator('button.knowledge-card').filter({ hasText: '周五晚上提醒我继续看项目' }).click();
    await page.getByText('时间还没确定。请先点“修改目标或时间”，明确日期、时间和时区，再确认安排。', {exact:true}).waitFor();
    assert.equal(await page.getByRole('button', {name:'确认目标和范围',exact:true}).count(),0);
    await page.getByRole('button', {name:'修改目标或时间',exact:true}).click();
    const date = new Date(Date.now()+3600000); const local = new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
    await page.locator('input[type="datetime-local"]').first().fill(local);
    await page.getByRole('button', {name:'保存草稿',exact:true}).click();
    await page.getByRole('button', {name:'确认目标和范围',exact:true}).click();
    await page.getByText('等待时间 · 第 3 版', {exact:true}).waitFor();
    list = await call('delegation.list', {});
    assert.equal(list[0].status,'scheduled'); assert.equal(list[0].spec.wait.kind,'time');
    await call('delegation.cancel', {delegation_id:list[0].id,revision:list[0].revision});
    await page.getByRole('button', {name:'陪伴',exact:true}).click();
    await page.getByRole('heading', {name:'现在怎样陪你',exact:true}).waitFor();
    await call('turn.send', {session_id:session.id,text:'我今天有点累，先听我讲就好',workflow_id:'source-digest',workflow_input:{sources:['note.txt']}});
    await page.getByText('先听你讲，少问一些', {exact:true}).waitFor({timeout:7000});
    await call('turn.send', {session_id:session.id,text:'今天不想聊工作',workflow_id:'source-digest',workflow_input:{sources:['note.txt']}});
    await page.getByText('尊重当前的话题边界', {exact:true}).waitFor({timeout:7000});
    const dialogue = await call('dialogue.get', {session_id:session.id});
    assert.equal(dialogue.boundaries.length,1);
    await call('dialogue.boundary.remove', {boundary_id:dialogue.boundaries[0].id});
    await page.getByRole('button', {name:'可以再聊这个了',exact:true}).waitFor({state:'detached',timeout:7000});
    console.log('PASS: open companionship panel follows natural listening and quiet phrasing plus boundary removal from other clients');
    console.log('PASS: user message → explicit reminder draft → no inferred time → edit/confirm → scheduled; original source retained');
  } finally {
    if (app) { await app.evaluate(({ dialog }) => { dialog.showMessageBox = async () => ({ response: 0 }); }).catch(() => {}); await app.close(); }
    rmSync(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
