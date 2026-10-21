// Render the production conversation with deterministic updates; no model or microphone access.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const { mkdtempSync, writeFileSync, rmSync } = require('node:fs');
const { resolve, basename } = require('node:path');

(async () => {
  const { createServer } = await import('vite');
  const root = resolve(__dirname, '..');
  const fixture = mkdtempSync(resolve(__dirname, '.scroll-'));
  writeFileSync(resolve(fixture, 'index.html'), `<div id="root"></div><script type="module">
    import React from 'react';
    import { createRoot } from 'react-dom/client';
    import { flushSync } from 'react-dom';
    import { Conversation } from '/src/components/Conversation.tsx';
    import '/src/styles.css';
    const root = createRoot(document.getElementById('root'));
    window.renderConversation = value => flushSync(() => root.render(React.createElement(Conversation, { ...value, onCancel: () => {} })));
  </script><style>#root { display:flex; flex-direction:column; height:380px; width:390px; } body { display:block; }</style>`);
  const server = await createServer({ root, configFile: false, server: { host: '127.0.0.1', port: 0 } });
  let browser;
  try {
    await server.listen();
    browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE || undefined });
    const page = await browser.newPage();
    await page.goto(`${server.resolvedUrls.local[0]}tests/${basename(fixture)}/index.html`);
    await page.waitForFunction(() => typeof window.renderConversation === 'function');
    const messages = Array.from({ length: 30 }, (_, index) => ({ id: `message-${index}`, session_id: 'one', role: 'assistant', content: `第 ${index} 条历史消息。这里是需要向上翻阅的聊天内容。` }));
    const task = { turn_id: 'stream', session_id: 'one', status: 'running', input_text: '继续聊天', output_text: '正在回答。' };
    let state = { sessionId: 'one', messages, tasks: [task] };
    const render = () => page.evaluate(value => window.renderConversation(value), state);
    const position = () => page.locator('.conversation').evaluate(element => ({ top: element.scrollTop, bottom: element.scrollHeight - element.clientHeight - element.scrollTop }));
    const settle = () => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await render(); await settle();
    assert.ok((await position()).bottom <= 2, 'Initial history opens at the bottom');
    await page.locator('.conversation').hover();
    await page.mouse.wheel(0, -700);
    await page.waitForFunction(() => { const e = document.querySelector('.conversation'); return e.scrollHeight - e.clientHeight - e.scrollTop > 500; });
    await settle();
    const reading = (await position()).top;
    for (let index = 0; index < 6; index++) {
      state = { ...state, tasks: [{ ...task, output_text: '新增的流式回答。'.repeat(index + 10) }] };
      await render(); await settle();
      assert.ok(Math.abs((await position()).top - reading) <= 2, 'Streaming and new task arrays preserve reading position');
    }
    state = { ...state, messages: [...messages, { id: 'new', session_id: 'one', role: 'assistant', content: '新的语音聊天回答。'.repeat(20) }], tasks: [{ ...task, status: 'completed' }] };
    await render(); await settle();
    assert.ok(Math.abs((await position()).top - reading) <= 2, 'Completed messages preserve reading position');
    await page.locator('.conversation').evaluate(element => { element.scrollTop = element.scrollHeight; });
    await settle();
    state = { ...state, messages: [...state.messages, { id: 'next', session_id: 'one', role: 'assistant', content: '回到底部后继续跟随。'.repeat(30) }] };
    await render(); await settle();
    assert.ok((await position()).bottom <= 2, 'Returning to bottom resumes following');
    await page.locator('.conversation').evaluate(element => { element.scrollTop = 200; });
    await settle();
    state = { ...state, sessionId: 'two', messages: messages.map(message => ({ ...message, session_id: 'two' })), tasks: [] };
    await render(); await settle();
    assert.ok((await position()).bottom <= 2, 'Switching sessions opens the latest message');
    const externalRequests = [];
    page.on('request', request => { if (request.url().includes('example.invalid')) externalRequests.push(request.url()); });
    await page.evaluate(() => {
      window.openedLinks = [];
      window.lobuddy = { subscribe: () => () => {}, openExternal: async url => { window.openedLinks.push(url); } };
    });
    state = { sessionId: 'security', tasks: [], messages: [{ id: 'unsafe', session_id: 'security', role: 'assistant',
      created_at: '2026-04-28T20:35:21', content: [
        '<script>window.rawExecuted = true</script>', '<iframe src="https://example.invalid/frame"></iframe>',
        '<p onclick="window.rawExecuted = true">raw markup</p>',
        '[bad scheme](javascript:alert(1))', '![remote image](https://example.invalid/image.png)',
        '**safe bold** and `safe code`', '[source link](https://example.invalid/source)',
      ].join('\n\n') }] };
    await render(); await settle();
    assert.equal(await page.locator('.message-content script, .message-content iframe, .message-content img, .message-content [onclick]').count(), 0);
    assert.equal(await page.locator('.message-content strong').innerText(), 'safe bold');
    assert.equal(await page.locator('.message-content code').innerText(), 'safe code');
    assert.equal(await page.locator('time').innerText(), '20:35');
    assert.equal(await page.evaluate(() => Boolean(window.rawExecuted)), false);
    assert.equal(await page.locator('.message-content a[href^="javascript:"]').count(), 0);
    const before = page.url();
    await page.getByRole('link', { name: 'source link' }).click();
    assert.deepEqual(await page.evaluate(() => window.openedLinks), ['https://example.invalid/source']);
    assert.equal(page.url(), before); assert.deepEqual(externalRequests, []);
    console.log('PASS: manual scroll, polling, completion and session reset; raw HTML/code/images blocked, Markdown retained, timestamp and controlled external links');
  } finally {
    await browser?.close(); await server.close(); rmSync(fixture, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
