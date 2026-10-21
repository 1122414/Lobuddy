const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { resolve } = require('node:path');
(async () => {
  const root = resolve(__dirname, '../..');
  const application = await electron.launch({ args: [resolve(__dirname, '..')], env: { ...process.env, LOBUDDY_DATA_DIR: resolve(root, '.local-upgrade/ts-voice-download/data'), LOBUDDY_WORKSPACE: resolve(root, '.local-upgrade/ts-voice-download/workspace') } });
  try {
    const page = await application.firstWindow();
    await page.getByText('服务已连接', { exact: true }).waitFor(); await page.bringToFront();
    await page.getByRole('button', { name: '设置', exact: true }).click();
    await page.getByRole('heading', { name: '连续语音陪伴', exact: true }).waitFor();
    const status = await page.evaluate(() => window.lobuddy.request('voice.get', {}, crypto.randomUUID()));
    if (!status.model_ready) {
      if (!process.argv.includes('--download')) throw Error('Run with --download to explicitly download the local model');
      await page.getByRole('button', { name: '下载本地语音模型', exact: true }).click();
      const deadline = Date.now() + 600000;
      let ready = false;
      while (Date.now() < deadline) {
        const state = await page.evaluate(() => window.lobuddy.request('voice.get', {}, crypto.randomUUID()));
        if (state.error) throw Error(state.error);
        if (state.model_ready) { ready = true; break; }
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      assert.equal(ready, true, 'Downloaded model must be verified ready');
    }
    assert.equal((await page.evaluate(() => window.lobuddy.request('voice.get', {}, crypto.randomUUID()))).fish_model, 's2.1-pro-free');
    await page.getByRole('heading', { name: '连续语音陪伴', exact: true }).scrollIntoViewIfNeeded();
    await page.locator('.voice-settings').screenshot({ path: '/tmp/lobuddy-p8-settings.png' });
    const rejected = await page.evaluate(async () => { try { await window.lobuddy.voicePermission(); return false; } catch { return true; } });
    assert.equal(rejected, true);
    console.log('PASS: explicit settings download validates fixed small model; free API visible; management window cannot request microphone');
  } finally { await application.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
