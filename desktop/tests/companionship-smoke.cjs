const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { waitFor } = require('./wait-for.cjs');
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { DatabaseSync } = require('node:sqlite');
const { resolve, join } = require('node:path');
(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-p7-ui-'));
  const env = { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace') };
  let application;
  try {
    application = await electron.launch({ args: isolatedDesktopArgs(temporary), env });
    let page = await application.firstWindow(); page.setDefaultTimeout(20000);
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.bringToFront();
    await page.getByRole('button', { name: '陪伴', exact: true }).click();
    await page.getByLabel('免打扰', { exact: true }).check();
    await page.getByRole('button', { name: '保存陪伴设置', exact: true }).click();
    await page.getByText('陪伴设置已保存。', { exact: true }).waitFor();
    const conversation = async name => {
      await page.getByLabel('如何称呼你', { exact: true }).fill(`请叫我${name}`);
      await page.getByRole('button', { name: '保存如何称呼你', exact: true }).click();
      await page.getByText('这条相处偏好已记住。', { exact: true }).waitFor();
      await page.getByRole('button', { name: '新对话', exact: true }).click();
      await page.getByLabel('消息', { exact: true }).fill('请只回答你应该怎样称呼我。');
      await page.getByRole('button', { name: '发送', exact: true }).click();
      await waitFor(page, async () => (await window.lobuddy.request('task.list', {}, crypto.randomUUID()))[0]?.status === 'completed', null, { timeout: 150000 });
      await page.locator('.message.assistant .message-content').filter({ hasText: name }).waitFor();
      await page.getByRole('button', { name: '陪伴', exact: true }).click();
    };
    await conversation('小叶');
    await conversation('阿澄');
    // A nickname alone is no longer a reason to interrupt. Supply an explicit experience,
    // and use the real idle worker/model to prepare a sourced invitation.
    await page.getByLabel('想一起记住的经历', { exact: true }).fill('今天散步时看到一只把树叶当帽子的小猫，给它取名叫叶子。');
    await page.getByRole('button', { name: '保存想一起记住的经历', exact: true }).click();
    await page.getByText('这条相处偏好已记住。', { exact: true }).waitFor();
    await page.evaluate(async () => {
      const current = await window.lobuddy.request('learning.get',{},crypto.randomUUID());
      await window.lobuddy.request('learning.configure',{ ...current.policy,idle_seconds: 1 },crypto.randomUUID());
      const policy = await window.lobuddy.request('companionship.get',{},crypto.randomUUID());
      await window.lobuddy.request('companionship.configure',policy,crypto.randomUUID());
    });
    let pet = application.windows().find(window => window.url().includes('surface=pet'));
    assert.ok(pet);
    assert.equal(await pet.getByRole('button', { name: '暂时不聊' }).count(), 0);
    await page.getByLabel('免打扰', { exact: true }).uncheck();
    await page.getByRole('button', { name: '保存陪伴设置', exact: true }).click();
    await page.getByText('陪伴设置已保存。', { exact: true }).waitFor();
    await waitFor(page, async () => !(await window.lobuddy.request('companionship.get', {}, crypto.randomUUID())).do_not_disturb);
    await application.close(); application = undefined;
    // Prepare only a trusted pending event while no service owns SQLite. This probe tests
    // native generation/display; macOS foreground activation is a separate physical gate.
    const pendingDb = new DatabaseSync(join(temporary,'data/lobuddy.db'));
    try {
      const state = JSON.parse(pendingDb.prepare("SELECT value FROM app_settings WHERE key='companion_policy_state'").get().value);
      const now = Date.now() / 1000;
      Object.assign(state,{ pending: 'app_returned',pending_at: now + 30,pending_expires: now + 1800,notice: null });
      pendingDb.prepare("UPDATE app_settings SET value=? WHERE key='companion_policy_state'").run(JSON.stringify(state));
      const learning = JSON.parse(pendingDb.prepare("SELECT value FROM app_settings WHERE key='learning_policy'").get().value);
      pendingDb.prepare("UPDATE app_settings SET value=? WHERE key='learning_policy'").run(JSON.stringify({ ...learning,enabled: false }));
    } finally { pendingDb.close(); }
    application = await electron.launch({ args: isolatedDesktopArgs(temporary),env });
    page = await application.firstWindow(); page.setDefaultTimeout(20000); page.on('pageerror',error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '陪伴', exact: true }).click();
    await page.evaluate(async () => {
      await window.lobuddy.request('companionship.activity',{ client: 'manage',typing: false,conversation: false },crypto.randomUUID());
      const state = await window.lobuddy.request('learning.get',{},crypto.randomUUID());
      await window.lobuddy.request('learning.configure',{ ...state.policy,enabled: true },crypto.randomUUID());
    });
    pet = application.windows().find(window => window.url().includes('surface=pet')); assert.ok(pet);
    await page.locator('.management-panel').evaluate(element => { element.scrollTop = 0; });
    await page.screenshot({ path: '/tmp/lobuddy-p7-settings.png' });
    await pet.getByRole('button', { name: '暂时不聊', exact: true }).waitFor({ timeout: 420000 }).catch(async error => {
      console.log('Pet state:', await pet.locator('body').innerText());
      console.log('Policy:', await page.evaluate(() => window.lobuddy.request('companionship.get', {}, crypto.randomUUID())));
      const db=new DatabaseSync(join(temporary,'data/lobuddy.db'),{readOnly:true});
      try {
        const diagnostics = { state: db.prepare("SELECT value FROM app_settings WHERE key='companion_policy_state'").get(),
          invitations: db.prepare('SELECT body FROM dialogue_invitation ORDER BY rowid DESC LIMIT 5').all(),
          jobs: db.prepare('SELECT kind,status,attempts,result,error FROM learning_job ORDER BY updated_at DESC LIMIT 10').all() };
        console.log(JSON.stringify(diagnostics));
        if (process.env.LOBUDDY_COMPANIONSHIP_REPORT) require('node:fs').writeFileSync(process.env.LOBUDDY_COMPANIONSHIP_REPORT,JSON.stringify({ passed: false,diagnostics },null,2)+'\n');
      } finally { db.close(); }
      throw error;
    });
    const invitation = await pet.locator('.bubble-content').innerText();
    assert.match(invitation,/小猫|树叶|叶子/); assert.doesNotMatch(invitation,/source_id|memory_id/);
    const prepared = await page.evaluate(() => window.lobuddy.request('learning.get',{},crypto.randomUUID()));
    assert.ok(prepared.jobs.some(job => job.kind === 'companion_topic' && job.status === 'completed' && job.result.prepared === true));
    await pet.screenshot({ path: '/tmp/lobuddy-p7-bubble.png', omitBackground: true });
    const native = await application.evaluate(({ BrowserWindow }) => {
      const pet = BrowserWindow.getAllWindows().find(window => window.webContents.getURL().includes('surface=pet'));
      return { focused: pet.isFocused(), focusable: pet.isFocusable() };
    });
    assert.deepEqual(native, { focused: false, focusable: false });
    await pet.getByRole('button', { name: '为什么提这个', exact: true }).click();
    await pet.getByRole('note', { name: '话题来源' }).waitFor();
    await pet.getByRole('button', { name: '暂时不聊', exact: true }).click();
    await pet.getByRole('button', { name: '暂时不聊', exact: true }).waitFor({ state: 'detached' });
    assert.equal(await pet.evaluate(() => window.lobuddy.request('companionship.poll', {}, crypto.randomUUID())), null);
    const forbidden = await page.evaluate(async () => { try { await window.lobuddy.request('companionship.trigger', { event: 'app_returned' }, crypto.randomUUID()); return false; } catch { return true; } });
    assert.equal(forbidden, true);
    assert.deepEqual(errors, []);
    await application.close();
    application = await electron.launch({ args: isolatedDesktopArgs(temporary), env });
    const reopened = await application.firstWindow();
    await reopened.getByText('服务已连接', { exact: true }).waitFor();
    await reopened.bringToFront();
    const remembered = await reopened.evaluate(() => window.lobuddy.request('memory.list', { query: '相处 · 称呼' }, crypto.randomUUID()));
    assert.equal(remembered.length, 1); assert.match(remembered[0].content, /阿澄/);
    await reopened.getByRole('button', { name: '陪伴', exact: true }).click();
    await reopened.getByRole('heading', { name: '偶尔主动，也懂得安静', exact: true }).waitFor().catch(async error => { console.log('Reopened state:', await reopened.locator('body').innerText()); throw error; });
    await reopened.getByLabel('如何称呼你', { exact: true }).fill('');
    await reopened.getByRole('button', { name: '保存如何称呼你', exact: true }).click();
    await reopened.getByText('这条相处记录已忘记。', { exact: true }).waitFor();
    const remaining = await reopened.evaluate(() => window.lobuddy.request('memory.list', { query: '相处 · 称呼' }, crypto.randomUUID()));
    assert.equal(remaining.length, 0);
    console.log('PASS: real model follows corrected nickname; reviewed sourced invitation, DND, no focus stealing, ignore, trusted trigger, persistence and preference deletion');
    if (process.env.LOBUDDY_COMPANIONSHIP_REPORT) require('node:fs').writeFileSync(process.env.LOBUDDY_COMPANIONSHIP_REPORT,JSON.stringify({ passed: true,offline_pending_event: true,invitation,checks: ['real-nickname-correction','real-reviewed-topic','dnd','no-focus-stealing','ignore','renderer-trigger-rejected','restart','preference-delete'] },null,2)+'\n');
  } finally { if (application) await application.close(); rmSync(temporary, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
