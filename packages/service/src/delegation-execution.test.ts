import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, writeFile, mkdir, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { requestSchemas, responseSchemas, type Method, type ResultsByMethod, TurnSendSchema } from '@lobuddy/contracts';
import { createApplicationService } from './application-service.js';
import type { Handler } from './rpc-server.js';
import { WorkspaceFiles } from './tools/files.js';
import { PracticalTools } from './tools/practical.js';
async function until(check: () => boolean) { const start = Date.now(); while (!check()) { if (Date.now() - start > 5000) throw Error('condition timed out'); await delay(5); } }
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-delegation-ts-'));
  const options = { kind: 'connect',storage: { data: join(root,'data'),workspace: join(root,'workspace'),logs: join(root,'logs'),create: true } };
  let service = await createApplicationService(options,() => {});
  async function call<M extends Method>(method: M,input: unknown = {},id: string = randomUUID()): Promise<ResultsByMethod[M]> {
    const handler = service.handlers[method] as Handler<M>; assert.ok(handler,method);
    return responseSchemas[method].parse(await handler(requestSchemas[method].parse(input) as Parameters<Handler<M>>[0],{ requestId: id,signal: new AbortController().signal })) as ResultsByMethod[M];
  }
  async function draft(changes: Record<string,unknown> = {}) {
    const created = await call('delegation.create',{ goal: '归纳指定资料',kind: 'source-digest',sources: ['source.txt'],criteria: ['资料来源覆盖且引用可追溯'],...changes });
    return call('delegation.confirm',{ delegation_id: created.id,revision: created.revision,expires_at: Date.now() / 1000 + 3600 });
  }
  await writeFile(join(root,'workspace/source.txt'),'决定：下周交付。\n待办：补充使用说明。');
  return { root,call,draft,service: () => service,restart: async () => { await service.close(); options.storage.create = false; service = await createApplicationService(options,() => {}); },
    close: async () => { await service.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('application executes a pinned digest without a model and atomically settles evidence, notification and completion only once',async () => {
  const f = await fixture();
  try {
    const value = await f.draft(),params = { delegation_id: value.id,revision: value.revision };
    const run = await f.call('delegation.run',params,'run'); await until(() => !f.service().tasks.busy);
    const detail = await f.call('delegation.get',{ delegation_id: value.id });
    assert.equal(detail.delegation.status,'completed'); assert.equal(detail.outcomes[0]!.verdict,'verified');
    assert.equal(detail.runs[0]!.workflow_version,'builtin-source-digest-1');
    const store = f.service().store;
    assert.equal(store.connection.prepare('SELECT count(*) n FROM delegation_event').get()!.n,1);
    assert.equal(store.connection.prepare('SELECT count(*) n FROM notification').get()!.n,1);
    const progress = await f.call('progress.get');
    assert.equal((await f.call('delegation.run',params,'run')).id,run.id);
    await f.restart(); assert.equal((await f.call('delegation.run',params,'run')).status,'completed');
    assert.deepEqual(await f.call('progress.get'),progress); assert.equal((await f.call('notification.list')).length,1);
  } finally { await f.close(); }
});
test('workflow writes require approval, rejection has no copy, and pausing cancels old execution authority',async () => {
  const f = await fixture();
  try {
    await mkdir(join(f.root,'workspace/inbox')); await writeFile(join(f.root,'workspace/inbox/a.txt'),'keep original');
    for (const action of ['reject','pause','approve']) {
      const value = await f.draft({ kind: 'organize-files',sources: [],source_directory: 'inbox',output_directory: 'out-' + action,criteria: ['副本数量和内容校验通过，原文件保留'] });
      await f.call('delegation.run',{ delegation_id: value.id,revision: value.revision });
      await until(() => f.service().tasks.approvals.list().length > 0);
      const approval = f.service().tasks.approvals.list()[0]!;
      if (action === 'pause') {
        const latest = (await f.call('delegation.get',{ delegation_id: value.id })).delegation;
        await f.call('delegation.pause',{ delegation_id: value.id,revision: latest.revision });
        assert.equal((await f.call('approval.resolve',{ approval_id: approval.approval_id,approved: true })).accepted,false);
      } else await f.call('approval.resolve',{ approval_id: approval.approval_id,approved: action === 'approve' });
      await until(() => !f.service().tasks.busy);
      if (action === 'approve') assert.equal(await readFile(join(f.root,'workspace/out-approve/txt/a.txt'),'utf8'),'keep original');
      else await assert.rejects(readFile(join(f.root,`workspace/out-${action}/txt/a.txt`)));
      const detail = await f.call('delegation.get',{ delegation_id: value.id });
      assert.equal(detail.delegation.status,action === 'pause' ? 'paused' : action === 'approve' ? 'completed' : 'failed');
    }
  } finally { await f.close(); }
});
test('durable readonly checkpoint resumes the same turn after restart, with one reply and reward; changed sources fail closed',async () => {
  const f = await fixture();
  try {
    for (const mode of ['unchanged', 'cached', 'changed', 'missing', 'expired', 'disabled']) {
      await writeFile(join(f.root,'workspace/source.txt'),'决定：下周交付。\n待办：补充使用说明。');
      const value = await f.draft(),tasks = f.service().tasks,repo = tasks.delegations;
      const session = await f.call('session.create',{ title: '恢复' });
      const run = repo.claim(randomUUID(),{ delegation_id: value.id,revision: value.revision },'builtin-source-digest-1').run;
      const turn = tasks.turns.submit(randomUUID(),TurnSendSchema.parse({ session_id: session.id,text: value.spec.goal,lane: 'background',workflow_id: value.spec.kind,workflow_input: { sources: value.spec.sources } }),state => {
        state.run_id = run.id; state.delegation_id = value.id; state.workflow_version = run.workflow_version; repo.bindWithinTransaction(run.id,state.turn_id);
      }).state;
      const hash = createHash('sha256').update(await readFile(join(f.root,'workspace/source.txt'))).digest('hex');
      let checkpoint: Record<string, unknown> = { input: turn.workflow_input };
      if (mode === 'cached') {
        const practical = new PracticalTools(new WorkspaceFiles(join(f.root, 'workspace'), []), tasks.ledger.outcomes, turn.turn_id,
          async () => false, () => true, new AbortController().signal);
        checkpoint = { ...checkpoint, digest: JSON.parse(await practical.digest({ sources: value.spec.sources, reuse_local_sources: false })) };
      }
      f.service().store.run('INSERT INTO delegation_checkpoint VALUES(?,?,?,?)',run.id,run.workflow_version,JSON.stringify({ 'source.txt': hash }),JSON.stringify(checkpoint));
      tasks.workflowExecution.startBudget(run.id,120); tasks.workflowExecution.reserve(run.id,12);
      await f.restart();
      const detail = await f.call('delegation.get',{ delegation_id: value.id }); assert.equal(detail.delegation.status,'needs_review');
      if (mode === 'changed') await writeFile(join(f.root,'workspace/source.txt'),'source changed');
      if (mode === 'missing') await rm(join(f.root, 'workspace/source.txt'));
      if (mode === 'expired') {
        detail.delegation.revision++;
        f.service().tasks.delegations.write({ ...detail.delegation, expires_at: Date.now() / 1000 - 1 });
      }
      if (mode === 'disabled') f.service().tasks.workflows.disable(run.workflow_version);
      const request = { delegation_id: value.id,revision: detail.delegation.revision,action: 'resume_readonly' };
      if (['changed', 'missing', 'expired', 'disabled'].includes(mode)) {
        await assert.rejects(f.call('delegation.recover',request));
        assert.equal((await f.call('delegation.get', { delegation_id: value.id })).delegation.status, 'needs_review');
      }
      else {
        await f.call('delegation.recover',request); await until(() => !f.service().tasks.busy);
        const done = await f.call('delegation.get',{ delegation_id: value.id }); assert.equal(done.delegation.status,'completed');
        assert.equal(done.runs[0]!.turn_id,turn.turn_id); assert.equal(done.outcomes[0]!.verdict,'verified');
        assert.equal((await f.call('session.history',{ session_id: session.id })).length,2);
        const usage = f.service().store.connection.prepare('SELECT * FROM delegation_usage WHERE run_id=?').get(run.id)!;
        assert.equal(usage.calls,mode === 'cached' ? 1 : 2); assert.equal(usage.started_at,null);
        const before = await f.call('progress.get'); await f.restart(); assert.deepEqual(await f.call('progress.get'),before);
      }
    }
  } finally { await f.close(); }
});
test('power suspension blocks new work and delivery, resume catches reminders without model or duplicate dispatch',async () => {
  const f = await fixture();
  try {
    const value = await f.draft({ kind: 'reminder',sources: [],criteria: ['通知按规则投递（不代表已读）'],wait: { kind: 'time',at: Date.now() / 1000 - 1,timezone: 'America/New_York' } });
    await f.call('runtime.power',{ suspended: true }); await f.service().scheduler.tick(); assert.equal((await f.call('notification.list')).length,0);
    await assert.rejects(f.call('delegation.run',{ delegation_id: value.id,revision: value.revision }));
    await f.call('runtime.power',{ suspended: false }); await f.service().scheduler.tick();
    assert.equal((await f.call('notification.list')).length,1); const batch = await f.call('notification.next'); assert.ok(batch);
    await f.call('notification.displayed',{ batch_id: batch.batch_id });
    assert.equal((await f.call('delegation.get',{ delegation_id: value.id })).delegation.status,'completed');
    await f.restart(); await f.service().scheduler.tick(); assert.equal((await f.call('notification.list')).length,1);
    assert.equal((await f.call('jev.status')).calls_today,0);
  } finally { await f.close(); }
});
test('settlement failure rolls back delegation completion and notification with the original task transaction',async () => {
  const f = await fixture();
  try {
    const value = await f.draft(),tasks = f.service().tasks,repo = tasks.delegations;
    const session = await f.call('session.create',{ title: '事务回归' });
    const run = repo.claim('reserved',{ delegation_id: value.id,revision: value.revision },'builtin-source-digest-1').run;
    const state = tasks.turns.submit('atomic',TurnSendSchema.parse({ session_id: session.id,text: value.spec.goal,lane: 'background' }),state => {
      state.run_id = run.id; state.delegation_id = value.id; repo.bindWithinTransaction(run.id,state.turn_id);
    }).state;
    state.status = 'completed'; state.output_text = '源文件证据';
    const { OutcomeSchema } = await import('@lobuddy/contracts');
    tasks.ledger.outcomes.save(OutcomeSchema.parse({ turn_id: state.turn_id,verdict: 'verified',scenario: 'digest',reason: '已核对来源' }));
    assert.throws(() => tasks.ledger.finish(state,() => { throw Error('fault before commit'); }),/fault/);
    assert.equal(repo.run(run.id).status,'running'); assert.equal(repo.get(value.id).status,'running');
    for (const table of ['notification','delegation_event','turn_settlement']) assert.equal(f.service().store.connection.prepare(`SELECT count(*) n FROM ${table}`).get()!.n,0);
    tasks.ledger.finish(state); tasks.ledger.finish(state);
    for (const table of ['notification','delegation_event','turn_settlement']) assert.equal(f.service().store.connection.prepare(`SELECT count(*) n FROM ${table}`).get()!.n,1);
  } finally { await f.close(); }
});
test('uncertain copies are inspected by source and target hash, never replayed, and emit one verified completion',async () => {
  const f = await fixture();
  try {
    const value = await f.draft({ kind: 'organize-files',sources: [],source_directory: 'inbox',output_directory: 'out',criteria: ['副本数量和内容校验通过，原文件保留'] });
    const tasks = f.service().tasks,repo = tasks.delegations;
    const session = await f.call('session.create',{ title: '未知副作用' });
    const run = repo.claim('reserved',{ delegation_id: value.id,revision: value.revision },'builtin-organize-files-1').run;
    const state = tasks.turns.submit('unknown-write',TurnSendSchema.parse({ session_id: session.id,text: value.spec.goal,lane: 'background' }),state => {
      state.run_id = run.id; state.delegation_id = value.id; repo.bindWithinTransaction(run.id,state.turn_id);
    }).state;
    await mkdir(join(f.root,'workspace/inbox')); await mkdir(join(f.root,'workspace/out'));
    const source = 'inbox/item.txt',target = 'out/item.txt'; await writeFile(join(f.root,'workspace',source),'same bytes');
    const sha256 = createHash('sha256').update('same bytes').digest('hex');
    tasks.ledger.outcomes.claimEffect('copy-effect',state.turn_id,JSON.stringify([{ source,target,sha256 }]));
    await f.restart(); const detail = await f.call('delegation.get',{ delegation_id: value.id });
    const request = { delegation_id: value.id,revision: detail.delegation.revision };
    await assert.rejects(f.call('delegation.recover',{ ...request,action: 'resume_readonly' }),/不得重放/);
    await assert.rejects(f.call('delegation.recover',request));
    await assert.rejects(readFile(join(f.root,'workspace',target)));
    await writeFile(join(f.root,'workspace',target),'damaged bytes');
    await assert.rejects(f.call('delegation.recover',request), /产物不符/);
    assert.equal(await readFile(join(f.root,'workspace',target),'utf8'),'damaged bytes');
    assert.equal(await readFile(join(f.root,'workspace',source),'utf8'),'same bytes');
    assert.equal((await f.call('delegation.get', { delegation_id: value.id })).delegation.status, 'needs_review');
    await writeFile(join(f.root,'workspace',target),'same bytes');
    const result = await f.call('delegation.recover',request);
    assert.equal(result.delegation.status,'completed'); assert.equal(result.outcomes[0]!.verdict,'verified');
    assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM delegation_event').get()!.n,1);
    assert.equal(f.service().tasks.busy,false);
  } finally { await f.close(); }
});
test('persistent call and elapsed budgets cannot reset when a delegation resumes',async () => {
  const f = await fixture();
  try {
    const execution = f.service().tasks.workflowExecution;
    assert.equal(execution.startBudget('budget',30),30); execution.reserve('budget',1);
    execution.finishBudget('budget'); execution.startBudget('budget',30);
    assert.throws(() => execution.reserve('budget',1),/预算已耗尽/);
    f.service().store.run('UPDATE delegation_usage SET spent=31 WHERE run_id=?','budget');
    assert.throws(() => execution.startBudget('budget',30),/时间预算已耗尽/);
  } finally { await f.close(); }
});
