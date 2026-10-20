// Native Electron + real Python; isolated records, no model requests or microphone.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const { execFileSync } = require('node:child_process');

(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-jev-ui-'));
  const root = resolve(__dirname, '../..');
  const env = { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace'), JEV_MODE: 'off', TYPESAFE_API_KEY: 'synthetic-not-used', LLM_API_KEY: 'synthetic-not-used', FISH_API_KEY: 'synthetic-not-used', LLM_MULTIMODAL_API_KEY: 'synthetic-not-used' };
  execFileSync(join(root, '.venv/bin/python'), ['-c', `
import sys
from pathlib import Path
from core.config import Settings
from core.storage.db import Database
from core.storage.notification_repo import NotificationRepository
from core.storage.jev_repo import JevRepository
from core.service.schedule_protocol import NotificationView
from core.service.jev_protocol import JevDecision
s=Settings(llm_api_key="synthetic",data_dir=Path(sys.argv[1]),workspace_path=Path(sys.argv[2]))
db=Database(s);db.init_database(allow_desktop=True)
NotificationRepository(db).put(NotificationView(id="synthetic",source_id="synthetic",reason="task_result",text="合成演示资料已完成",planned_at=1000.0,created_at=1000.0))
r=JevRepository(db)
d=JevDecision(action="quiet",reason="内容重复，仅留收件箱（合成演示）",mode="shadow",status="decided",created_at=1000.0,not_before=1600.0,model="jev-1.13.0")
r.reserve("synthetic","",d,1,30,60000)
`, env.LOBUDDY_DATA_DIR, env.LOBUDDY_WORKSPACE], { cwd: root, env });
  let application;
  const errors = [];
  try {
    application = await electron.launch({ args: [resolve(__dirname, '..')], env, timeout: 30000 });
    const page = await application.firstWindow();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByLabel('Jev 模式', { exact: true }).waitFor();
    assert.equal(await page.getByLabel('Jev 模式').inputValue(), 'off');
    await page.getByRole('button', { name: '设置TypeSafe Jev凭据', exact: true }).waitFor();
    await page.getByLabel('Jev 模式').selectOption('shadow');
    await page.waitForFunction(() => !document.querySelector('select[aria-label="Jev 模式"]').disabled);
    const status = await page.evaluate(() => window.lobuddy.request('jev.status', {}, crypto.randomUUID()));
    assert.equal(status.mode, 'shadow');
    const settings = await page.evaluate(() => window.lobuddy.request('settings.get', {}, crypto.randomUUID()));
    assert.equal('typesafe_api_key' in settings.values, false);
    assert.equal(JSON.stringify(settings).includes('synthetic-not-used'), false);
    await page.getByLabel('Jev 模式').selectOption('off');
    await page.waitForFunction(() => !document.querySelector('select[aria-label="Jev 模式"]').disabled);
    await page.reload();
    await page.getByText('服务已连接', { exact: true }).waitFor();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    assert.equal(await page.getByLabel('Jev 模式').inputValue(), 'off');
    await page.getByRole('button', { name: '通知', exact: true }).click();
    await page.getByText('合成演示资料已完成', { exact: true }).waitFor();
    await page.getByText('Jev 提示判断 · 仅观察', { exact: true }).click();
    await page.getByText('内容重复，仅留收件箱（合成演示）', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    console.log('PASS: Jev settings, live mode, reload persistence, opaque key and decision evidence');
  } finally {
    if (application) await application.close();
    rmSync(temporary, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
