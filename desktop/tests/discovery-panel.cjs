// Production panel with synthetic IPC; this checks reconciliation, not public network access.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync,writeFileSync,rmSync } = require('node:fs');
const { resolve,basename } = require('node:path');

(async () => {
  const { createServer } = await import('vite');
  const root = resolve(__dirname,'..'), fixture = mkdtempSync(resolve(__dirname,'.discovery-'));
  writeFileSync(resolve(fixture,'index.html'), `<div id="root"></div><script type="module">
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import { flushSync } from 'react-dom';
    import { DiscoveryPanel } from '/src/components/DiscoveryPanel.tsx';
    import '/src/styles.css';
    window.discoveryView = { policy: { revision: 1,enabled: true,interests: ['AI 陪伴'],repositories: ['moeru-ai/airi'] },
      items: [],attempts: [],used: 0,daily_limit: 6,reading: false };
    window.calls = []; window.opened = [];
    window.lobuddy = {
      request: async (method,params) => {
        window.calls.push(method);
        if (method === 'discovery.get') {
          const value = structuredClone(window.discoveryView);
          if (window.holdRead) { window.holdRead = false; await new Promise(resolve => { window.releaseRead = resolve; }); }
          return value;
        }
        if (method === 'discovery.configure') {
          if (params.revision !== window.discoveryView.policy.revision) throw Error('stale policy');
          window.discoveryView = { ...window.discoveryView,policy: {...params,revision: params.revision + 1},items: [],reading: false };
        }
        if (method === 'discovery.refresh') window.discoveryView.reading = true;
        return structuredClone(window.discoveryView);
      },
      openExternal: async url => { window.opened.push(url); }
    };
    const root = createRoot(document.getElementById('root'));
    window.mount = () => flushSync(() => root.render(React.createElement(DiscoveryPanel)));
    window.unmount = () => flushSync(() => root.render(null)); window.mount();
  </script>`);
  const server = await createServer({root,configFile: false,server: {host: '127.0.0.1',port: 0}});
  let browser;
  try {
    await server.listen(); browser = await chromium.launch({executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined});
    const page = await browser.newPage(); page.setDefaultTimeout(10000);
    const errors = [],external = []; page.on('pageerror',error => errors.push(error.message));
    page.on('request',request => { if (request.url().includes('example.invalid')) external.push(request.url()); });
    await page.goto(`${server.resolvedUrls.local[0]}tests/${basename(fixture)}/index.html`);
    await page.waitForFunction(() => document.querySelector('[aria-label="资讯兴趣"]').value === 'AI 陪伴');
    await page.getByLabel('资讯兴趣',{exact: true}).fill('我尚未保存的兴趣');
    await page.evaluate(() => {
      window.discoveryView.used = 1;
      window.discoveryView.items = [{id: 'release',repository: 'moeru-ai/airi',title: '合成发布',
        text: '<img src="https://example.invalid/remote">只作文本展示',url: 'https://github.com/moeru-ai/airi/releases/tag/synthetic',
        published_at: Date.now()/1000 - 60,checked_at: Date.now()/1000,expires_at: Date.now()/1000 + 60}];
    });
    await page.getByRole('heading',{name: 'moeru-ai/airi · 合成发布'}).waitFor();
    assert.equal(await page.getByLabel('资讯兴趣',{exact: true}).inputValue(),'我尚未保存的兴趣');
    assert.equal(await page.locator('article img').count(),0); assert.deepEqual(external,[]);
    await page.getByRole('button',{name: '查看官方原文',exact: true}).click();
    assert.deepEqual(await page.evaluate(() => window.opened),['https://github.com/moeru-ai/airi/releases/tag/synthetic']);
    await page.evaluate(() => { window.discoveryView.items = []; });
    await page.getByRole('heading',{name: 'moeru-ai/airi · 合成发布'}).waitFor({state: 'detached'});
    await page.getByRole('button',{name: '检查新发布',exact: true}).click();
    await page.getByText('正在检查公开发布，可离开此页面。',{exact: true}).waitFor();
    assert.equal(await page.getByRole('button',{name: '保存兴趣来源',exact: true}).isEnabled(),true);
    await page.evaluate(() => { window.discoveryView.reading = false; });
    await page.getByText('已检查可更新的来源；近期读过的项目会保留间隔。',{exact: true}).waitFor();
    await page.evaluate(() => { window.discoveryView.policy = { ...window.discoveryView.policy,revision: 2,interests: ['其他窗口的兴趣'] }; window.discoveryView.used = 2; });
    await page.getByText(/今天已尝试读取 2\/6 次/).waitFor();
    await page.getByRole('button',{name: '保存兴趣来源',exact: true}).click();
    await page.getByText('兴趣来源已在其他窗口更新，请重新打开后再修改。',{exact: true}).waitFor();
    assert.equal(await page.evaluate(() => window.calls.filter(method => method === 'discovery.configure').length),0);
    await page.evaluate(() => { window.unmount(); window.mount(); });
    await page.waitForFunction(() => document.querySelector('[aria-label="资讯兴趣"]').value === '其他窗口的兴趣');
    await page.evaluate(() => { window.holdRead = true; });
    await page.waitForFunction(() => typeof window.releaseRead === 'function');
    await page.getByLabel('资讯兴趣',{exact: true}).fill('已经保存的新兴趣');
    await page.getByRole('button',{name: '保存兴趣来源',exact: true}).click();
    await page.getByText('兴趣来源已保存，空闲时会查找新的正式发布。',{exact: true}).waitFor();
    await page.evaluate(() => window.releaseRead());
    await page.getByRole('button',{name: '保存兴趣来源',exact: true}).click();
    await page.waitForFunction(() => window.discoveryView.policy.revision === 4);
    assert.equal(await page.evaluate(() => window.discoveryView.policy.revision),4,'late polling cannot replace the saved revision');
    await page.evaluate(() => window.unmount());
    const count = await page.evaluate(() => window.calls.length);
    await new Promise(resolve => setTimeout(resolve,2100));
    assert.equal(await page.evaluate(() => window.calls.length),count); assert.deepEqual(errors,[]);
    console.log('PASS: background/expiry reconciliation, unsaved edits, nonblocking refresh, cross-window revision, late response, plain text and controlled links, unmount');
  } finally { await browser?.close(); await server.close(); rmSync(fixture,{recursive: true,force: true}); }
})().catch(error => { console.error(error); process.exitCode = 1; });
