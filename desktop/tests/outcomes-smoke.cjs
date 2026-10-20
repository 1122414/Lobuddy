const { _electron: electron } = require('playwright');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { execFileSync } = require('node:child_process');
const { tmpdir } = require('node:os');
const { join, resolve } = require('node:path');
const assert = require('node:assert/strict');

(async () => {
  const root = resolve(__dirname, '../..');
  const temp = mkdtempSync(join(tmpdir(), 'lobuddy-e3-ui-'));
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
from core.storage.service_repo import ServiceRepository
from core.service.protocol import TurnSend
from core.service.outcomes import OutcomeRepository, Outcome
k.chat.get_or_create_session('fixture')
r=ServiceRepository(d)
t,_,_=r.submit('test-result',TurnSend(session_id='fixture',text='合成文件整理验收'))
t.status='completed';r.save(t)
OutcomeRepository(d).save(Outcome(turn_id=t.turn_id,verdict='verified',scenario='organize',criteria=['副本数量与 SHA-256 一致'],reason='已验证1份测试副本',evidence=[{'sha256':'test-only'}]))
`, temp], { cwd: root, stdio: 'pipe' });
    const bootstrap = join(temp, 'start.cjs');
    writeFileSync(bootstrap, `const {app}=require('electron');app.setPath('userData',${JSON.stringify(join(temp, 'electron'))});app.setAppPath(${JSON.stringify(join(root, 'desktop'))});require(${JSON.stringify(join(root, 'desktop/dist-electron/desktop/electron/main.js'))});`);
    app = await electron.launch({ args: [bootstrap], env: { ...process.env,
      LOBUDDY_DATA_DIR: join(temp, 'data'), LOBUDDY_WORKSPACE: join(temp, 'workspace') } });
    const page = await app.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '任务', exact: true }).click();
    await page.getByText('执行结束', {exact: true}).waitFor();
    await page.getByText('结果已验证', {exact: true}).click();
    await page.getByText('副本数量与 SHA-256 一致', {exact: true}).waitFor();
    await page.getByText('已验证1份测试副本', {exact: true}).waitFor();
    console.log('PASS E3 UI: execution status separated from result, criteria and evidence visible');
  } finally { if (app) await app.close(); rmSync(temp, { recursive: true, force: true }); }
})().catch(error => { console.error(error); process.exitCode = 1; });
