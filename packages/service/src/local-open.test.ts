import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, rm, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import childProcess from 'node:child_process';
import { EventEmitter } from 'node:events';
import { syncBuiltinESMExports } from 'node:module';
import { TurnStateSchema } from '@lobuddy/contracts';
import { LocalOpen, openNative } from './tools/local.js';
import { GovernedTools } from './tools/governed.js';
import { runtimeSettings } from './config/settings.js';
import { Store } from './storage/database.js';
import { OutcomeRepository } from './storage/outcomes.js';
import type { Approvals } from './tasks/approvals.js';

test('local candidates exclude scripts and links and cannot be reused after replacement or another lookup', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'lobuddy-local-open-')));
  try {
    const file = join(root, 'lobuddy-synthetic-candidate.txt'); await writeFile(file, 'hello');
    await writeFile(join(root, 'lobuddy-synthetic-candidate.sh'), 'exit 0');
    await symlink(file, join(root, 'lobuddy-synthetic-candidate-link.txt'));
    const local = new LocalOpen(root, join(root, 'home'));
    assert.deepEqual(local.resolve('lobuddy-synthetic-candidate').map(item => item.path), [file]);
    assert.equal(local.validate(file), file); assert.throws(() => local.validate('/Applications/Unknown.app'));
    await writeFile(file, 'changed'); assert.throws(() => local.validate(file));
    local.resolve('lobuddy-synthetic-candidate'); assert.equal(local.validate(file), file);
    local.resolve('another-query'); assert.throws(() => local.validate(file));
    assert.throws(() => local.resolve('   '));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('local open requires approval and unchanged candidates, uses one argv dispatch and an isolated environment', async () => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'lobuddy-local-approval-'))), workspace = join(root, 'workspace');
  await mkdir(workspace); const file = join(workspace, 'lobuddy-synthetic-candidate with spaces.txt'); await writeFile(file, 'hello');
  const store = new Store(join(root, 'lobuddy.db'), { create: true });
  const settings = runtimeSettings({ data: root, workspace, logs: join(root, 'logs') });
  const state = TurnStateSchema.parse({ task_id: 'task', turn_id: 'turn', session_id: 'session', engine_id: 'engine', input_text: '打开文件', lane: 'foreground', status: 'running' });
  let allowed = false, change = false, active = true, requests = 0;
  const approvals = { request: async () => { requests++; if (change) await writeFile(file, 'changed during approval'); return allowed; } } as unknown as Approvals;
  const dispatched: { command: string; argv: string[]; options: childProcess.SpawnOptions }[] = [];
  mock.method(childProcess, 'spawn', ((command: string, argv: string[], options: childProcess.SpawnOptions) => {
    dispatched.push({ command, argv, options }); const child = new EventEmitter(); queueMicrotask(() => child.emit('exit', 0)); return child;
  }) as typeof childProcess.spawn); syncBuiltinESMExports();
  const old = process.env.LLM_API_KEY; process.env.LLM_API_KEY = 'synthetic-must-not-be-inherited';
  try {
    const create = () => new GovernedTools(state, settings, approvals, new OutcomeRepository(store), new AbortController().signal, () => active, join(root, 'app'));
    const resolve = (tools: GovernedTools) => tools.execute({ callId: 'lookup', name: 'lobuddy_local_resolve', arguments: { query: 'lobuddy-synthetic-candidate' } });
    const open = (tools: GovernedTools, callId = 'open') => tools.execute({ callId, name: 'lobuddy_local_open', arguments: { path: file } });
    let tools = create(); await resolve(tools); await assert.rejects(open(tools), /未获批准/); assert.equal(dispatched.length, 0);
    allowed = true; tools = create(); await resolve(tools); await open(tools);
    assert.equal(dispatched.length, 1); assert.equal(dispatched[0]!.command, '/usr/bin/open'); assert.deepEqual(dispatched[0]!.argv, [file]);
    assert.deepEqual(Object.keys(dispatched[0]!.options.env!).sort(), ['HOME', 'LANG', 'PATH']);
    assert.doesNotMatch(JSON.stringify(dispatched), /synthetic-must-not-be-inherited/);
    await assert.rejects(open(tools, 'again'), /一次/); assert.equal(dispatched.length, 1);
    tools = create(); await assert.rejects(open(tools), /候选/); assert.equal(requests, 2);
    tools = create(); await resolve(tools); change = true; await assert.rejects(open(tools), /未变化/); assert.equal(dispatched.length, 1);
    active = false; await assert.rejects(create().execute({ callId: 'inactive', name: 'lobuddy_local_resolve', arguments: { query: 'candidate' } }));
    const abort = new AbortController(); abort.abort(); await assert.rejects(openNative(file, abort.signal)); assert.equal(dispatched.length, 1);
  } finally {
    if (old === undefined) delete process.env.LLM_API_KEY; else process.env.LLM_API_KEY = old;
    mock.restoreAll(); syncBuiltinESMExports(); store.close(); await rm(root, { recursive: true, force: true });
  }
});
