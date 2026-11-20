const { isolatedDesktopArgs } = require('./isolated-desktop.cjs');
const { waitFor } = require('./wait-for.cjs');
const { _electron: electron } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync,rmSync,writeFileSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { join,resolve } = require('node:path');

(async () => {
  const temporary = mkdtempSync(join(tmpdir(),'lobuddy-discovery-ui-'));
  const env = { ...process.env,LOBUDDY_DATA_DIR: join(temporary,'data'),LOBUDDY_WORKSPACE: join(temporary,'workspace') };
  const report = { started_at: new Date().toISOString(),checks: [],public_releases: [],passed: false };
  let app;
  let phase = 'launch';
  const launch = () => electron.launch({ args: isolatedDesktopArgs(temporary),env,timeout: 120000 });
  const call = (page,method,params = {}) => page.evaluate(({method,params}) => window.lobuddy.request(method,params,crypto.randomUUID()),{method,params});
  try {
    app = await launch(); phase = 'service-ready'; let page = await app.firstWindow();
    await page.getByText('服务已连接',{exact: true}).waitFor({timeout: 30000});
    phase = 'open-companionship';
    await page.getByRole('button',{name: '陪伴',exact: true}).click();
    phase = 'read-default';
    assert.equal((await call(page,'discovery.get')).policy.enabled,false);
    const memoriesBefore = await call(page,'memory.list');
    report.checks.push('default-off');
    phase = 'configure';
    await page.getByLabel('免打扰',{exact: true}).check();
    await page.getByRole('button',{name: '保存陪伴设置',exact: true}).click();
    await page.getByText('陪伴设置已保存。',{exact: true}).waitFor();
    await page.getByLabel('资讯兴趣',{exact: true}).fill('AI 陪伴\n开源项目\n创作工具');
    await page.getByLabel('资讯项目',{exact: true}).fill('moeru-ai/airi\nProject-N-E-K-O/N.E.K.O\nComfy-Org/ComfyUI');
    await page.getByLabel('允许查找这些项目的新发布',{exact: true}).check();
    await page.getByRole('button',{name: '保存兴趣来源',exact: true}).click();
    await page.getByText('兴趣来源已保存，空闲时会查找新的正式发布。',{exact: true}).waitFor();
    report.checks.push('native-explicit-configuration');
    phase = 'public-read';
    await page.getByRole('button',{name: '检查新发布',exact: true}).click();
    await page.getByText('已检查可更新的来源；近期读过的项目会保留间隔。',{exact: true}).waitFor({timeout: 120000});
    const first = await call(page,'discovery.get'); report.attempts = first.attempts;
    report.public_releases = first.items.map(({repository,title,url,published_at}) => ({repository,title,url,published_at}));
    assert.ok(first.items.some(item => item.repository === 'moeru-ai/airi'),'AIRI must yield an actual recent stable release');
    assert.ok(first.items.some(item => item.repository === 'comfy-org/comfyui'),'ComfyUI must yield an actual recent stable release');
    assert.equal(first.used,3); assert.equal(new Set(first.items.map(item => item.id)).size,first.items.length);
    for (const item of first.items) {
      assert.ok(item.published_at <= Date.now() / 1000 && item.expires_at > Date.now() / 1000);
      assert.match(item.url,/^https:\/\/github\.com\//);
    }
    report.checks.push('manual-read-during-dnd','actual-public-release-dates','canonical-official-links');
    await page.getByRole('button',{name: '检查新发布',exact: true}).click();
    await waitFor(page,async () => !(await window.lobuddy.request('discovery.get',{},crypto.randomUUID())).reading,null,{timeout: 30000});
    assert.equal((await call(page,'discovery.get')).used,first.used); report.checks.push('manual-refresh-does-not-reset-interval');
    phase = 'screenshot';
    const panel = page.getByRole('region',{name: '兴趣新鲜事',exact: true});
    await panel.getByRole('heading',{level: 3}).scrollIntoViewIfNeeded();
    for (const item of first.items) await panel.getByRole('heading',{name: `${item.repository} · ${item.title}`,exact: true}).waitFor();
    assert.equal(await panel.getByRole('button',{name: '查看官方原文',exact: true}).count(),first.items.length);
    report.checks.push('native-release-titles-and-original-links');
    if (process.env.LOBUDDY_DISCOVERY_SCREENSHOT) {
      const path = resolve(process.env.LOBUDDY_DISCOVERY_SCREENSHOT); await page.screenshot({path});
      await panel.getByRole('heading',{name: `${first.items[0].repository} · ${first.items[0].title}`,exact: true}).scrollIntoViewIfNeeded();
      await page.screenshot({path: path.replace(/\.png$/iu,'.releases.png')});
    }
    phase = 'restart'; await app.close(); app = await launch(); page = await app.firstWindow();
    await page.getByText('服务已连接',{exact: true}).waitFor({timeout: 30000});
    await page.getByRole('button',{name: '陪伴',exact: true}).click();
    const restarted = await call(page,'discovery.get'); assert.equal(restarted.used,first.used);
    assert.deepEqual(restarted.items.map(item => item.id),first.items.map(item => item.id));
    report.checks.push('restart-retains-cache-and-budget');
    phase = 'disable';
    await page.getByLabel('允许查找这些项目的新发布',{exact: true}).uncheck();
    await page.getByRole('button',{name: '保存兴趣来源',exact: true}).click();
    await page.getByText('已停止发现新内容，并清除缓存。',{exact: true}).waitFor();
    const disabled = await call(page,'discovery.get'); assert.equal(disabled.items.length,0); assert.equal(disabled.policy.enabled,false);
    assert.equal((await call(page,'discovery.refresh')).used,first.used);
    report.checks.push('disable-clears-cache-and-stops-reads');
    phase = 'memory-boundary';
    const memoriesAfter = await call(page,'memory.list');
    report.memory_counts = { before: memoriesBefore.length,after: memoriesAfter.length };
    assert.deepEqual(memoriesAfter,memoriesBefore);
    report.checks.push('public-content-does-not-write-user-memory');
    report.passed = true;
  } catch (error) {
    report.phase = phase;
    report.failure = error instanceof assert.AssertionError ? error.message : 'native_discovery_check_failed';
    // This fixture only uses public releases and synthetic local settings; no model call or provider error is printed.
    if (phase !== 'public-read') report.diagnostic = String(error?.message ?? '').replace(/(?:Bearer\s+|sk-)[A-Za-z0-9._-]+/gu,'[redacted]').slice(0,300);
    throw error;
  } finally {
    report.completed_at = new Date().toISOString();
    if (process.env.LOBUDDY_DISCOVERY_REPORT) writeFileSync(process.env.LOBUDDY_DISCOVERY_REPORT,JSON.stringify(report,null,2)+'\n');
    if (app) await app.close(); rmSync(temporary,{recursive: true,force: true});
  }
})().catch(error => { console.error(error instanceof assert.AssertionError ? error.message : 'Native discovery verification failed'); process.exitCode = 1; });
