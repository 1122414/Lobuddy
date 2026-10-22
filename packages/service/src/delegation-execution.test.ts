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

test('an unsubmitted reservation survives restart as editable review without replay, then requires fresh confirmation',async () => {
  const f = await fixture();
  try {
    const value = await f.draft(),params = { delegation_id: value.id,revision: value.revision };
    const run = f.service().tasks.delegations.claim('never-submitted',params,'builtin-source-digest-1').run;
    await f.restart();
    const detail = await f.call('delegation.get',{ delegation_id: value.id });
    assert.equal(detail.delegation.status,'needs_review');
    assert.equal(detail.delegation.active_run_id,'');
    assert.match(detail.delegation.reason,/未提交.*重新确认/);
    assert.equal(detail.runs[0]!.id,run.id); assert.equal(detail.runs[0]!.status,'interrupted');
    assert.equal(detail.runs[0]!.turn_id,''); assert.equal(detail.runs[0]!.verdict,'unknown');
    assert.equal((await f.call('delegation.run',params,'never-submitted')).id,run.id);
    assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM service_turn').get()!.n,0);
    await f.restart();
    assert.deepEqual(await f.call('delegation.get',{ delegation_id: value.id }),detail);
    await assert.rejects(f.call('delegation.run',{ delegation_id: value.id,revision: detail.delegation.revision }),/尚未就绪/);
    const draft = await f.call('delegation.edit',{ delegation_id: value.id,revision: detail.delegation.revision,spec: detail.delegation.spec });
    assert.equal(draft.status,'draft'); assert.equal(draft.authorized_at,null); assert.equal(draft.expires_at,null);
    const confirmed = await f.call('delegation.confirm',{ delegation_id: draft.id,revision: draft.revision,expires_at: Date.now() / 1000 + 3600 });
    const fresh = await f.call('delegation.run',{ delegation_id: confirmed.id,revision: confirmed.revision });
    assert.notEqual(fresh.id,run.id); await until(() => !f.service().tasks.busy);
    const done = await f.call('delegation.get',{ delegation_id: value.id });
    assert.equal(done.delegation.status,'completed'); assert.equal(done.runs.length,2);
    assert.equal(done.runs.find(item => item.id === run.id)!.status,'interrupted');
    assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM service_turn').get()!.n,1);
  } finally { await f.close(); }
});

test('submission failure releases only the unsubmitted reservation and repeated request never submits again',async () => {
  const f = await fixture();
  try {
    const value = await f.draft(),params = { delegation_id: value.id,revision: value.revision },tasks = f.service().tasks;
    const submit = tasks.submit; let attempted = 0;
    tasks.submit = async () => { attempted++; throw Error('synthetic failure before task transaction'); };
    try { await assert.rejects(f.call('delegation.run',params,'failed-submit'),/synthetic failure/); }
    finally { tasks.submit = submit; }
    const detail = await f.call('delegation.get',{ delegation_id: value.id });
    assert.equal(detail.delegation.status,'needs_review'); assert.equal(detail.delegation.active_run_id,'');
    assert.equal((await f.call('delegation.run',params,'failed-submit')).status,'interrupted');
    assert.equal(attempted,1);
    for (const table of ['service_turn','task_effect','turn_settlement']) assert.equal(f.service().store.connection.prepare(`SELECT count(*) n FROM ${table}`).get()!.n,0);
  } finally { await f.close(); }
});

test('inconsistent SQL, JSON or durable task binding never releases an uncertain reservation',async () => {
  const f = await fixture();
  try {
    for (const mode of ['sql','json','task-run','task-request']) {
      const value = await f.draft(),tasks = f.service().tasks,repo = tasks.delegations,store = f.service().store;
      const run = repo.claim('uncertain-' + mode,{ delegation_id: value.id,revision: value.revision },'builtin-source-digest-1').run;
      if (mode === 'sql') store.run('UPDATE delegation_run SET turn_id=? WHERE id=?','unknown-turn',run.id);
      if (mode === 'json') store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify({ ...run,turn_id: 'unknown-turn' }),run.id);
      if (mode.startsWith('task-')) {
        const session = await f.call('session.create',{ title: '绑定不一致' });
        tasks.turns.submit(mode === 'task-request' ? 'delegation-run-' + run.id : randomUUID(),
          TurnSendSchema.parse({ session_id: session.id,text: value.spec.goal,lane: 'background' }),state => {
            if (mode === 'task-run') state.run_id = run.id;
          });
      }
      repo.recover(run.id);
      const latest = repo.get(value.id);
      assert.equal(latest.active_run_id,run.id); assert.equal(latest.status,'needs_review');
      assert.doesNotMatch(latest.reason,/未提交/);
      assert.throws(() => repo.change('blocked-edit-' + mode,'edit',{ delegation_id: value.id,revision: latest.revision,spec: latest.spec }),/核对/);
    }
  } finally { await f.close(); }
});

test('an expired pending dispatch preserves its specific review reason without attempting a run',async context => {
  let now = Date.now(); context.mock.method(Date,'now',() => now);
  const f = await fixture();
  try {
    const value = await f.draft({ wait: { kind: 'time',at: now / 1000 + 10 } });
    f.service().scheduler.repo.tick(); now += 11000;
    const dispatches = f.service().scheduler.repo.tick();
    assert.equal(dispatches.length,1);
    assert.equal((await f.call('delegation.get',{ delegation_id: value.id })).delegation.status,'ready');
    now += 3600000;
    await f.service().scheduler.tick();
    const detail = await f.call('delegation.get',{ delegation_id: value.id });
    assert.equal(detail.delegation.status,'needs_review'); assert.match(detail.delegation.reason,/授权已到期/);
    assert.equal(detail.runs.length,0);
    assert.equal(f.service().store.connection.prepare('SELECT done FROM schedule_dispatch WHERE trigger_id=?').get(dispatches[0]!.trigger)!.done,1);
    await f.service().scheduler.tick();
    assert.deepEqual(await f.call('delegation.get',{ delegation_id: value.id }),detail);
    assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM service_turn').get()!.n,0);
  } finally { await f.close(); }
});

test('persisted interrupted reservations from older versions are repaired once only when no task was bound',async () => {
  for (const mode of ['unbound','bound']) {
    const f = await fixture();
    try {
      const value = await f.draft(),tasks = f.service().tasks,repo = tasks.delegations;
      const run = repo.claim('legacy-reservation',{ delegation_id: value.id,revision: value.revision },'builtin-source-digest-1').run;
      if (mode === 'bound') {
        const session = await f.call('session.create',{ title: '旧版关联执行' });
        tasks.turns.submit('legacy-bound',TurnSendSchema.parse({ session_id: session.id,text: value.spec.goal,lane: 'background' }),state => {
          state.run_id = run.id; state.delegation_id = value.id; repo.bindWithinTransaction(run.id,state.turn_id);
        });
      }
      const oldRun = { ...repo.run(run.id),status: 'interrupted',verdict: 'unknown',finished_at: repo.clock(),reason: '服务中断，尚未核实结果；不自动重放' };
      f.service().store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(oldRun),run.id);
      const previous = repo.get(value.id);
      repo.write({ ...previous,status: 'needs_review',revision: previous.revision + 1,reason: oldRun.reason });
      await f.restart();
      const detail = await f.call('delegation.get',{ delegation_id: value.id });
      assert.equal(detail.delegation.active_run_id,mode === 'unbound' ? '' : run.id);
      assert.equal(detail.delegation.status,'needs_review');
      assert.equal(detail.runs[0]!.finished_at,oldRun.finished_at); assert.equal(detail.runs[0]!.status,'interrupted');
      if (mode === 'bound') assert.deepEqual(detail.runs[0],oldRun);
      await f.restart();
      assert.deepEqual(await f.call('delegation.get',{ delegation_id: value.id }),detail);
      if (mode === 'bound') {
        await assert.rejects(f.call('delegation.edit',{ delegation_id: value.id,revision: detail.delegation.revision,spec: detail.delegation.spec }),/核对/);
        continue;
      }
      assert.match(detail.delegation.reason,/未提交.*重新确认/);
      assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM service_turn').get()!.n,0);
      const draft = await f.call('delegation.edit',{ delegation_id: value.id,revision: detail.delegation.revision,spec: detail.delegation.spec });
      const confirmed = await f.call('delegation.confirm',{ delegation_id: draft.id,revision: draft.revision,expires_at: Date.now() / 1000 + 3600 });
      const fresh = await f.call('delegation.run',{ delegation_id: value.id,revision: confirmed.revision });
      assert.notEqual(fresh.id,run.id); await until(() => !f.service().tasks.busy);
      assert.equal((await f.call('delegation.get',{ delegation_id: value.id })).delegation.status,'completed');
      assert.equal(f.service().store.connection.prepare('SELECT count(*) n FROM service_turn').get()!.n,1);
    } finally { await f.close(); }
  }
});

test('legacy reservation repair preserves paused, cancelled, replaced and inconsistent execution ownership',async () => {
  const f = await fixture();
  try {
    for (const mode of ['paused','cancelled','replaced','sql','notification'] as const) {
      const value = await f.draft(),repo = f.service().tasks.delegations;
      const run = repo.claim('legacy-blocked-' + mode,{ delegation_id: value.id,revision: value.revision },'builtin-source-digest-1').run;
      const interrupted = { ...run,status: 'interrupted',finished_at: repo.clock(),reason: '旧执行等待核对',
        workflow_version: mode === 'notification' ? 'notification' : run.workflow_version };
      f.service().store.run('UPDATE delegation_run SET turn_id=?,body=? WHERE id=?',mode === 'sql' ? 'unknown-turn' : null,JSON.stringify(interrupted),run.id);
      const previous = repo.get(value.id);
      repo.write({ ...previous,status: mode === 'paused' || mode === 'cancelled' ? mode : 'needs_review',revision: previous.revision + 1,
        active_run_id: mode === 'replaced' ? 'another-run' : run.id,reason: interrupted.reason });
      const before = await f.call('delegation.get',{ delegation_id: value.id });
      repo.recover(run.id); repo.recover(run.id);
      assert.deepEqual(await f.call('delegation.get',{ delegation_id: value.id }),before);
    }
  } finally { await f.close(); }
});
