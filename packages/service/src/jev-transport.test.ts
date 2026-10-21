import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import https from 'node:https';
import type { IncomingMessage, ClientRequest, RequestOptions } from 'node:http';
import { Readable, Writable } from 'node:stream';
import { syncBuiltinESMExports } from 'node:module';
import { decideJev, jevRequestBody } from './engine/jev.js';

const answer = { type: 'choice', choice: 'yes', confidence: 1, probabilities: { yes: 1, no: 0, unknown: 0 } };
const valid = JSON.stringify({ model: 'jev-1.13.0', answers: { relevant: answer, time_sensitive: answer, duplicate: answer }, usage: { input_tokens: 12, output_tokens: 0 } });

test('Jev HTTP uses one fixed authenticated endpoint, rejects redirects and bounds response parsing without exposing secrets', async () => {
  let status = 200, payload = Buffer.from(valid), networkFailure = false, silent = false;
  const calls: { url: string; options: RequestOptions; body: Buffer }[] = [];
  const replacement = (url: string, options: RequestOptions, callback: (response: IncomingMessage) => void) => {
    const chunks: Buffer[] = [];
    const call = new Writable({ write(chunk, _encoding, done) { chunks.push(Buffer.from(chunk)); done(); },
      final(done) {
        calls.push({ url, options, body: Buffer.concat(chunks) }); done();
        queueMicrotask(() => {
          if (networkFailure) { call.destroy(Error('synthetic-private-response')); return; }
          if (silent) return;
          callback(Object.assign(Readable.from([payload]), { statusCode: status, headers: { location: 'https://evil.invalid' } }) as IncomingMessage);
        });
      } });
    options.signal?.addEventListener('abort', () => call.destroy(Error('synthetic-private-abort')), { once: true });
    return call as unknown as ClientRequest;
  };
  mock.method(https, 'request', replacement as typeof https.request); syncBuiltinESMExports();
  try {
    const body = jevRequestBody({ notification: '资料完成', goal: '资料', recent_delivered: [] }, 'jev-1.13.0');
    assert.equal((await decideJev(body, 'synthetic-key', new AbortController().signal)).answers.time_sensitive.choice, 'yes');
    assert.equal(calls.length, 1); assert.equal(calls[0]!.url, 'https://api.typesafe.ai/v1/systemone');
    assert.equal((calls[0]!.options.headers as Record<string, string>).Authorization, 'Bearer synthetic-key');
    assert.equal(calls[0]!.options.agent, false); assert.deepEqual(calls[0]!.body, body);
    for (const code of [302, 401, 402, 429, 500]) {
      status = code; payload = Buffer.from('synthetic-private-response'); const before: number = calls.length;
      await assert.rejects(decideJev(body, 'synthetic-key', new AbortController().signal), { message: `http_${code}` });
      assert.equal(calls.length, before + 1);
    }
    status = 200;
    for (const invalid of ['not json', 'x'.repeat(65537), '{"answers":{}}']) {
      payload = Buffer.from(invalid);
      await assert.rejects(decideJev(body, 'synthetic-key', new AbortController().signal), { message: 'invalid_response' });
    }
    networkFailure = true;
    await assert.rejects(decideJev(body, 'synthetic-key', new AbortController().signal), { message: 'network_or_timeout' });
    networkFailure = false; silent = true;
    const owner = new AbortController(), cancelled = decideJev(body, 'synthetic-key', owner.signal);
    owner.abort(); await assert.rejects(cancelled, { message: 'network_or_timeout' });
    mock.timers.enable({ apis: ['setTimeout'] });
    const expired = decideJev(body, 'synthetic-key', new AbortController().signal);
    mock.timers.tick(4000); await assert.rejects(expired, { message: 'network_or_timeout' });
  } finally { mock.timers.reset(); mock.restoreAll(); syncBuiltinESMExports(); }
});
