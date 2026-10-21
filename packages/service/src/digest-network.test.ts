import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import https from 'node:https';
import type { IncomingMessage, ClientRequest, RequestOptions } from 'node:http';
import { Readable, Writable } from 'node:stream';
import { syncBuiltinESMExports } from 'node:module';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DigestArgumentsSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { OutcomeRepository } from './storage/outcomes.js';
import { WorkspaceFiles } from './tools/files.js';
import { PracticalTools } from './tools/practical.js';

test('optimized digests refetch duplicate links and preserve each changed source independently', async () => {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-digest-network-'));
  const store = new Store(join(root, 'data.db'), { create: true }); let calls = 0;
  const replacement = (_url: URL, _options: RequestOptions, callback: (response: IncomingMessage) => void) => {
    const request = new Writable({ write(_chunk, _encoding, done) { done(); }, final(done) {
      calls++; const body = `决定：第${calls}次读取链接。`;
      queueMicrotask(() => callback(Object.assign(Readable.from([Buffer.from(body)]), {
        statusCode: 200, headers: { 'content-type': 'text/plain' },
      }) as IncomingMessage)); done();
    } });
    return request as unknown as ClientRequest;
  };
  mock.method(https, 'request', replacement as typeof https.request); syncBuiltinESMExports();
  try {
    const outcomes = new OutcomeRepository(store);
    const tools = new PracticalTools(new WorkspaceFiles(root, []), outcomes, 'links', async () => false,
      () => true, new AbortController().signal);
    await tools.digest(DigestArgumentsSchema.parse({ sources: ['https://8.8.8.8/a', 'https://8.8.8.8/a'], reuse_local_sources: true }));
    const outcome = outcomes.get('links');
    assert.equal(calls, 2); assert.equal(outcome.verdict, 'verified');
    assert.equal(outcome.metrics.physical_reads, 2); assert.equal(outcome.metrics.cache_hits, 0);
    assert.deepEqual(outcome.evidence.slice(0, 2).map(item => item.ref), ['S1', 'S2']);
    assert.notEqual(outcome.evidence[0]!.sha256, outcome.evidence[1]!.sha256);
  } finally { mock.restoreAll(); syncBuiltinESMExports(); store.close(); await rm(root, { recursive: true, force: true }); }
});
