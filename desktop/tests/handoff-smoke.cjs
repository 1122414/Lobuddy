const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, mkdirSync, rmSync, writeFileSync } = require('node:fs');
const { join } = require('node:path');
const { tmpdir } = require('node:os');
const { DatabaseSync } = require('node:sqlite');
const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { waitFor } = require('./wait-for.cjs');

(async () => {
  const root = mkdtempSync(join(tmpdir(), 'lobuddy-handoff-native-'));
  const data = join(root, 'data'), workspace = join(root, 'workspace'); mkdirSync(workspace);
  const report = { started_at: new Date().toISOString(), kind: 'native-real-model-handoff', rounds: [], checks: [] };
  let app;
  try {
    const { Store } = await import('../../packages/service/dist/storage/database.js');
    const { Preferences } = await import('../../packages/service/dist/storage/preferences.js');
    const { ChatRepository } = await import('../../packages/service/dist/storage/chat.js');
    const { KnowledgeService } = await import('../../packages/service/dist/knowledge/service.js');
    const { ProjectService } = await import('../../packages/service/dist/knowledge/projects.js');
    const { runtimeSettings } = await import('../../packages/service/dist/config/settings.js');
    const { ChatSessionSchema, SourceShareSchema, ProjectCreateSchema, CompanionPolicyStateSchema } = await import('@lobuddy/contracts');
    const store = new Store(join(data, 'lobuddy.db'), { create: true });
    const settings = runtimeSettings({ data, workspace, logs: join(root,'logs') });
    const knowledge = new KnowledgeService(store, () => settings), projects = new ProjectService(store, knowledge.relationship, new AbortController().signal);
    const target = projects.repo.create('target', ProjectCreateSchema.parse({ name: '星桥项目' }));
    const unrelated = projects.repo.create('other', ProjectCreateSchema.parse({ name: '其他项目' }));
    const chat = new ChatRepository(store); chat.saveSession(ChatSessionSchema.parse({ id: 'other-session', title: '原先的会话' }));
    projects.repo.bind('other-session', unrelated.id, 0);
    const source = await projects.share('source', SourceShareSchema.parse({ project_id: target.id, category: 'pending', title: '星桥的选择',
      text: '星桥项目上次决定保留离线功能。下一步准备先断网启动一次，看看能不能打开已有记录。这个测试还没有做。' }));
    const now = Date.now() / 1000, preferences = new Preferences(store);
    preferences.set('learning_policy', JSON.stringify({ enabled: false }));
    preferences.set('companion_policy_state', JSON.stringify(CompanionPolicyStateSchema.parse({ pending: 'app_returned', pending_at: now + 20, pending_expires: now + 3600 })));
    // Prepare a deterministic sourced invitation offline; topic generation is a separate stage.
    store.run('INSERT INTO dialogue_invitation VALUES(?,?,?,?,?,?,?)', 'prepared', 'app_returned', `project:${source.id}`, String(source.revision),
      `project:${target.id}:pending`, JSON.stringify({ opening: '想到你之前说的', closing: '想接着聊时，我在。', start: 0, length: Math.min(60,[...source.text].length) }), now + 3600);
    store.close();
    // Exercise the actual Electron v3 → v4 opening path, with an untouched v3 snapshot retained.
    const old = new DatabaseSync(join(data,'lobuddy.db'));
    old.exec("DROP TABLE companion_context_use; DROP TABLE companion_handoff; DELETE FROM ts_migration WHERE id='002-companion-handoff'; PRAGMA user_version=3"); old.close();
    const env = { ...process.env, LOBUDDY_DATA_DIR: data, LOBUDDY_WORKSPACE: workspace };
    const launch = () => electron.launch({ args: isolatedDesktopArgs(root), env });
    app = await launch(); let page = await app.firstWindow(); page.setDefaultTimeout(25000);
    await page.getByText('服务已连接', { exact: true }).waitFor();
    const call = (method, params = {}) => page.evaluate(([method,params]) => window.lobuddy.request(method,params,crypto.randomUUID()),[method,params]);
    assert.equal((await call('service.health')).model_configured, true, 'real model must be configured');
    await page.getByRole('button', { name: '陪伴', exact: true }).click();
    await page.evaluate(() => localStorage.setItem('lobuddy-session','other-session'));
    const pet = app.windows().find(window => window.url().includes('surface=pet')); assert.ok(pet);
    await pet.locator('.bubble-content').filter({ hasText: '星桥项目' }).waitFor({ timeout: 50000 });
    const notice = await pet.evaluate(() => window.lobuddy.request('companionship.poll',{},crypto.randomUUID())); assert.ok(notice?.memory_id);
    const visibleControls = await pet.locator('.pet-bubble button').evaluateAll(buttons => buttons.every(button => {
      const box = button.getBoundingClientRect(); return box.x >= 0 && box.y >= 0 && box.right <= innerWidth && box.bottom <= innerHeight;
    }));
    assert.equal(visibleControls,true,'long sourced text must not push bubble controls outside the pet viewport');
    await pet.getByRole('button',{ name: '为什么提这个',exact: true }).click();
    await pet.getByRole('note',{ name: '话题来源' }).waitFor();
    await pet.getByRole('button',{ name: '为什么提这个',exact: true }).click();
    await pet.getByRole('note',{ name: '话题来源' }).waitFor({ state: 'detached' });
    report.checks.push('long-bubble-controls-stay-visible','source-preview-toggles-within-bubble');
    await pet.locator('.bubble-content').click();
    const quick = await waitForPage(app, 'surface=quick');
    await quick.getByText(notice.text, { exact: true }).waitFor();
    const sessionId = await quick.evaluate(() => localStorage.getItem('lobuddy-session'));
    assert.notEqual(sessionId, 'other-session');
    assert.equal((await call('project.selection',{ session_id: sessionId })).project_id,target.id);
    const replay = await pet.evaluate(id => window.lobuddy.request('companionship.accept',{ notice_id: id },crypto.randomUUID()),notice.notice_id);
    assert.equal(replay.session_id,sessionId);
    assert.equal((await call('session.history',{ session_id: sessionId })).length,1);
    assert.equal((await call('session.history',{ session_id: 'other-session' })).length,0);
    report.checks.push('native-v3-upgrade','bubble-click-routes-correct-project','duplicate-click-one-utterance');
    for (const [input, expected] of [['后来呢？', /星桥|离线|断网/], ['你刚提的那个决定是什么？', /离线/], ['那下一步先试什么？', /断网|启动/]]) {
      await quick.getByLabel('消息', { exact: true }).fill(input);
      await quick.getByRole('button', { name: '发送', exact: true }).click();
      const state = await waitFor(quick, async ({ sessionId,input }) => {
        const tasks = await window.lobuddy.request('task.list',{},crypto.randomUUID());
        return tasks.find(task => task.session_id === sessionId && task.input_text === input && !['queued','running'].includes(task.status));
      }, { sessionId,input }, { timeout: 150000 });
      assert.equal(state.status,'completed'); assert.match(state.output_text,expected);
      report.rounds.push({ input, output: state.output_text });
    }
    report.checks.push('three-real-model-short-followups');
    await app.close(); app = await launch(); page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    const reopenedPet = app.windows().find(window => window.url().includes('surface=pet'));
    const persisted = await reopenedPet.evaluate(id => window.lobuddy.request('companionship.accept',{ notice_id: id },crypto.randomUUID()),notice.notice_id);
    assert.equal(persisted.session_id,sessionId);
    assert.equal((await call('session.history',{ session_id: sessionId })).filter(m => m.content === notice.text).length,1);
    await call('source.forget',{ source_id: source.id,revision: source.revision });
    assert.ok(!(await call('session.history',{ session_id: sessionId })).some(m => m.content === notice.text));
    assert.equal(await reopenedPet.evaluate(async id => { try { await window.lobuddy.request('companionship.accept',{ notice_id: id },crypto.randomUUID()); return false; } catch { return true; } },notice.notice_id),true);
    report.checks.push('restart-retains-handoff','forget-removes-utterance-and-refuses-replay');
    report.completed_at = new Date().toISOString(); report.passed = true;
    if (process.env.LOBUDDY_HANDOFF_REPORT) writeFileSync(process.env.LOBUDDY_HANDOFF_REPORT,JSON.stringify(report,null,2)+'\n');
    console.log(JSON.stringify(report,null,2));
  } finally {
    if (app) { await app.evaluate(({dialog}) => { dialog.showMessageBox = async () => ({ response: 0 }); }).catch(() => {}); await app.close(); }
    rmSync(root,{ recursive: true,force: true });
  }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
async function waitForPage(app, part) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    const found = app.windows().find(page => page.url().includes(part)); if (found) return found;
    await new Promise(resolve => setTimeout(resolve,100));
  }
  throw Error('Quick chat did not open');
}
