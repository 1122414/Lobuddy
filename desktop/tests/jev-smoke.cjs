const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
// Native Electron + TypeScript; isolated records, no model requests or microphone.
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, rmSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');

(async () => {
  const temporary = mkdtempSync(join(tmpdir(), 'lobuddy-jev-ui-'));
  const env = { ...process.env, LOBUDDY_DATA_DIR: join(temporary, 'data'), LOBUDDY_WORKSPACE: join(temporary, 'workspace'), JEV_MODE: 'off', TYPESAFE_API_KEY: 'synthetic-not-used', LLM_API_KEY: 'synthetic-not-used', FISH_API_KEY: 'synthetic-not-used', LLM_MULTIMODAL_API_KEY: 'synthetic-not-used' };
  await (await import('./fixtures.mjs')).seedFixture('jev',temporary);
  env.LLM_MODEL='synthetic-model';
  let application;
  const errors = [];
  try {
    application = await electron.launch({ args: isolatedDesktopArgs(temporary), env, timeout: 30000 });
    const page = await application.firstWindow();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    await page.getByText('服务已连接', { exact: true }).waitFor();
    assert.equal((await page.evaluate(()=>window.lobuddy.request('service.health',{},crypto.randomUUID()))).model_configured,false,'Stored empty model must override environment fallback');
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
    assert.equal(settings.credentials.llm_api_key,true,'A saved key is present even before choosing a model');
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
