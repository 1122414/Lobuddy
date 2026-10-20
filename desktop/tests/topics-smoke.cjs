const { _electron: electron } = require('playwright');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-e2-ui-'));
  let app;
  try {
    execFileSync(join(root, '.venv/bin/python'), ['-c', `
import sys
from pathlib import Path
from core.config import Settings
from core.storage.db import Database
from core.service.knowledge import KnowledgeService
from core.models.chat import ChatMessage
s=Settings(llm_api_key='test', _env_file=None, data_dir=Path(sys.argv[1])/'data', workspace_path=Path(sys.argv[1])/'workspace', memory_enable_migration=False)
s.workspace_path.mkdir()
d=Database(s); d.init_database(allow_desktop=True)
k=KnowledgeService(s,d)
k.record_focus('focus-fixture',25)
from core.service.companionship import Companionship
c=Companionship(d)
choice=c.topics.choose(); assert choice
c.topics.shown(choice); c.topics.feedback(choice.topic_id,'never')
`, temp], { cwd: root, stdio: 'pipe' });
    const bootstrap = join(temp, 'start.cjs');
    writeFileSync(bootstrap, `const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temp, 'electron'))});app.setAppPath(${JSON.stringify(join(root, 'desktop'))});require(${JSON.stringify(join(root, 'desktop/dist-electron/desktop/electron/main.js'))});`);
    app = await electron.launch({ args: [bootstrap], env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace') } });
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '记忆', exact: true }).click();
    const panel = page.getByRole('region', { name: '相处话题' });
    await panel.getByText('不再主动提起', { exact: true }).waitFor();
    await panel.getByRole('button', { name: '允许再次主动聊' }).click();
    await panel.getByRole('button', { name: '允许再次主动聊' }).waitFor({ state: 'hidden' });
    const topics = await page.evaluate(() => window.lobuddy.request('companionship.topics', {}, crypto.randomUUID()));
    assert.equal(topics[0].blocked, false);
    await page.getByRole('button', { name: '成长', exact: true }).click();
    await page.getByText('历程徽章', { exact: true }).waitFor();
    await page.getByText('还没有通过结果验证的技能记录。', { exact: true }).waitFor();
    assert.equal(await page.getByText('尚未解锁', { exact: true }).count(), 0);
    console.log('PASS E2: grounded experience, persistent topic feedback/unblock, honest progress UI');
  } finally { if (app) await app.close(); rmSync(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
