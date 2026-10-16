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
    console.log('PASS: manual scroll persists across streaming, polling and completion; bottom-follow resumes; session switch resets');
  } finally {
    await browser?.close(); await server.close(); rmSync(fixture, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
