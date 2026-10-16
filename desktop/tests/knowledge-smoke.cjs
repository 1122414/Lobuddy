// Real Electron/Python management acceptance. All records are disposable test data.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync, readFileSync, existsSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-p4-ui-'));
  const application = await electron.launch({ args: [resolve(__dirname, '..')],
    env: { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace') }, timeout: 30000 });
  const errors = [];
  try {
    const page = await application.firstWindow();
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].setSize(1536, 1024));
    await page.getByRole('button', { name: '记忆', exact: true }).click();
    await page.getByRole('button', { name: '添加记忆', exact: true }).click();
    await page.getByLabel('标题', { exact: true }).fill('喜欢的茶');
    await page.getByLabel('记忆内容', { exact: true }).fill('工作的时候，喜欢喝一杯白桃乌龙茶。');
    await page.getByRole('button', { name: '保存记忆', exact: true }).click();
    await page.locator('.notice').waitFor();
    const memory = (await page.evaluate(() => window.lobuddy.request('memory.list', { query: '白桃乌龙茶' }, crypto.randomUUID())))[0];
    assert.ok(memory.id);
    await page.getByText('查看来源', { exact: true }).click();
    await page.getByText(memory.id, { exact: true }).waitFor();
    await page.getByLabel('记忆内容', { exact: true }).fill('工作的时候，现在喜欢喝桂花红茶。');
    await page.getByRole('button', { name: '保存记忆', exact: true }).click();
    await page.waitForFunction(async id => (await window.lobuddy.request('memory.list', { query: '桂花红茶' }, crypto.randomUUID()))[0]?.id === id, memory.id);
    await page.screenshot({ path: '/tmp/lobuddy-p4-memory.png' });
    assert.match(readFileSync(join(temporary, 'workspace/USER.md'), 'utf8'), /桂花红茶/);
    await page.getByRole('button', { name: '删除记忆', exact: true }).click();
    await page.getByRole('button', { name: '保留', exact: true }).click();
    assert.equal((await page.evaluate(() => window.lobuddy.request('memory.list', { query: '桂花红茶' }, crypto.randomUUID()))).length, 1);
    await page.getByRole('button', { name: '删除记忆', exact: true }).click();
    await page.getByRole('button', { name: '确认删除', exact: true }).click();
    await page.getByText('记忆已删除。', { exact: true }).waitFor();
    assert.doesNotMatch(readFileSync(join(temporary, 'workspace/USER.md'), 'utf8'), /桂花红茶/);
    console.log('PASS: memory create, source, edit preserving ID, keep/delete and projection clearing');

    await page.getByRole('button', { name: '技能', exact: true }).click();
    await page.getByRole('button', { name: '添加技能', exact: true }).click();
    await page.getByLabel('技能名称', { exact: true }).fill('tea-break');
    await page.getByLabel('适用场景', { exact: true }).fill('休息时，一起安排一杯茶的时间');
    const content = '---\nname: tea-break\ndescription: Plan a tea break.\n---\n\n## When to use\nUse this skill when the user requests a tea break.\n\n## Steps\n1. Ask how long the break should last.\n2. Suggest a quiet moment and a cup of tea.\n';
    await page.getByLabel('技能正文', { exact: true }).fill(content);
    await page.getByRole('button', { name: '保存技能', exact: true }).click();
    await page.getByRole('button', { name: '停用技能', exact: true }).waitFor();
    await page.screenshot({ path: '/tmp/lobuddy-p4-skills.png' });
    await page.getByRole('button', { name: '停用技能', exact: true }).click();
    await page.getByRole('button', { name: '启用技能', exact: true }).waitFor();
    assert.equal(existsSync(join(temporary, 'workspace/skills/tea-break/SKILL.md')), false);
    await page.getByLabel('技能正文', { exact: true }).fill(content + '\n3. Return to work gently.\n');
    await page.getByRole('button', { name: '保存技能', exact: true }).click();
    await page.getByText('已保存，后续对话会使用更新后的内容。', { exact: true }).waitFor();
    assert.equal(existsSync(join(temporary, 'workspace/skills/tea-break/SKILL.md')), false);
    await page.reload();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '技能', exact: true }).click();
    await page.locator('.knowledge-card').filter({ hasText: 'tea-break' }).click();
    assert.match(await page.getByLabel('技能正文', { exact: true }).inputValue(), /Return to work gently/);
    await page.getByRole('button', { name: '启用技能', exact: true }).click();
    await page.getByRole('button', { name: '停用技能', exact: true }).waitFor();
    assert.match(readFileSync(join(temporary, 'workspace/skills/tea-break/SKILL.md'), 'utf8'), /Return to work gently/);
    console.log('PASS: skill create, disable, edit while disabled, reload and re-enable');
    await page.getByRole('button', { name: '历史', exact: true }).click();
    await page.getByRole('region', { name: '历史检索' }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: history navigation and no renderer errors');
  } catch (error) {
    const page = application.windows().find(item => !item.isClosed());
    if (page) { console.log(await page.locator('main').innerText()); console.log(await page.locator('label').allTextContents()); await page.screenshot({ path: '/tmp/lobuddy-p4-ui-failure.png' }); }
    throw error;
  } finally { await application.close(); rmSync(temporary, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
