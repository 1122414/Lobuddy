import { randomUUID } from 'node:crypto';
import { DelegationSpecSchema, DelegationViewSchema, DelegationRunSchema, DelegationDetailSchema,
  type DelegationSpec, type DelegationView, type DelegationRun, type DelegationChange,
  type DelegationConfirm, type DelegationEdit } from '@lobuddy/contracts';
import { delegationJson } from '@lobuddy/domain';
import { Store } from './database.js';
import { parseStoredJson } from './json.js';
export class DelegationRepository {
  constructor(readonly store: Store, readonly clock = () => Date.now() / 1000) { store.run('INSERT OR IGNORE INTO delegation_schema VALUES(1)'); }
  get(id: string): DelegationView {
    const row = this.store.connection.prepare('SELECT body FROM delegation WHERE id=?').get(id);
    if (!row) throw Error('委托不存在'); return DelegationViewSchema.parse(parseStoredJson(String(row.body)));
  }
  list(): DelegationView[] {
    return this.store.connection.prepare('SELECT body FROM delegation ORDER BY rowid DESC').all().map(row => DelegationViewSchema.parse(parseStoredJson(String(row.body))));
  }
  // Callers own the transaction that includes the revision and accompanying durable effect.
  write(input: DelegationView): void {
    const value = DelegationViewSchema.parse(input), body = JSON.stringify(value);
    this.store.run('INSERT INTO delegation VALUES(?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',value.id,body);
    this.store.run('INSERT INTO delegation_revision VALUES(?,?,?)',value.id,value.revision,body);
  }
  private replay(id: string, fingerprint: string): unknown | undefined {
    const row = this.store.connection.prepare('SELECT fingerprint,result FROM delegation_request WHERE id=?').get(id);
    if (row && row.fingerprint !== fingerprint) throw Error('请求 ID 已用于不同委托操作');
    return row ? parseStoredJson(String(row.result)) : undefined;
  }
  private remember(id: string, fingerprint: string, value: DelegationView | DelegationRun): void {
    this.store.run('INSERT INTO delegation_request VALUES(?,?,?)',id,fingerprint,JSON.stringify(value));
  }
  create(id: string, input: DelegationSpec): DelegationView {
    const spec = DelegationSpecSchema.parse(input), fingerprint = 'create:' + delegationJson(spec);
    return this.store.transaction(() => {
      const previous = this.replay(id,fingerprint); if (previous) return DelegationViewSchema.parse(previous);
      if (spec.session_id && !this.store.connection.prepare('SELECT 1 FROM chat_session WHERE id=?').get(spec.session_id)) throw Error('来源会话不存在');
      if (spec.source_message_id && !this.store.connection.prepare("SELECT 1 FROM chat_message WHERE id=? AND session_id=? AND role='user'").get(spec.source_message_id,spec.session_id)) throw Error('来源必须是指定会话中的用户消息');
      const value = DelegationViewSchema.parse({ id: randomUUID(),revision: 1,spec,created_at: this.clock(),updated_at: this.clock() });
      this.write(value); this.remember(id,fingerprint,value); return value;
    });
  }
  detail(id: string) {
    return DelegationDetailSchema.parse({ delegation: this.get(id),
      runs: this.store.connection.prepare('SELECT body FROM delegation_run WHERE delegation_id=? ORDER BY rowid DESC').all(id).map(row => parseStoredJson(String(row.body))),
      revisions: this.store.connection.prepare('SELECT body FROM delegation_revision WHERE id=? ORDER BY revision DESC').all(id).map(row => parseStoredJson(String(row.body))),
    });
  }
  private check(value: DelegationView, revision: number): void {
    if (value.revision !== revision) throw Error('委托已更新，请重新读取后操作');
    if (['completed','cancelled','failed'].includes(value.status)) throw Error('委托已结束，请新建委托');
  }
  private ready(value: DelegationView): void {
    const states = { none: 'ready',time: 'scheduled',user: 'waiting_user',event: 'waiting_event' } as const;
    value.status = states[value.spec.wait.kind]; value.reason = '已确认；仅在约定范围与有效期内执行，写入仍须审批';
  }
  change(id: string, action: string, params: DelegationChange | DelegationConfirm | DelegationEdit): DelegationView {
    const fingerprint = action + ':' + delegationJson(params);
    return this.store.transaction(() => {
      const previous = this.replay(id,fingerprint); if (previous) return DelegationViewSchema.parse(previous);
      const value = this.get(params.delegation_id); this.check(value,params.revision); const now = this.clock();
      if (action === 'confirm' && 'expires_at' in params) {
        if (value.status !== 'draft' || params.expires_at <= now) throw Error('只能确认有效期在未来的草稿');
        if (value.spec.wait.at && value.spec.wait.at >= params.expires_at) throw Error('授权有效期必须晚于提醒时间');
        value.authorized_at = now; value.expires_at = params.expires_at; this.ready(value);
      } else if (action === 'pause') {
        if (['draft','paused'].includes(value.status)) throw Error('当前状态不能暂停');
        value.status = 'paused'; value.reason = '已暂停；已发生的操作不会自动撤销';
      } else if (action === 'cancel') { value.status = 'cancelled'; value.reason = '已取消，不再调度；既有产物保留'; }
      else if (action === 'resume') {
        if (value.status !== 'paused' || !value.expires_at || value.expires_at <= now) throw Error('只有仍获授权的暂停委托可以继续');
        if (value.active_run_id) throw Error('上次执行需要先核对；不能自动重放'); this.ready(value);
      } else if (action === 'edit' && 'spec' in params) {
        if (value.status === 'running' || value.active_run_id) throw Error('请先暂停并核对已发生的操作');
        if (params.spec.session_id !== value.spec.session_id || params.spec.source_message_id !== value.spec.source_message_id) throw Error('原始委托来源不能被替换');
        value.spec = params.spec; value.authorized_at = value.expires_at = null;
        value.status = 'draft'; value.reason = '目标或范围已变更，需要重新确认';
      } else throw Error('不支持的委托状态转换');
      value.revision++; value.updated_at = now; this.write(value); this.remember(id,fingerprint,value); return value;
    });
  }
  claim(trigger: string, params: DelegationChange, version: string): { run: DelegationRun; created: boolean } {
    const fingerprint = 'run:' + delegationJson(params);
    return this.store.transaction(() => {
      const previous = this.replay(trigger,fingerprint); if (previous) return { run: this.run(DelegationRunSchema.parse(previous).id),created: false };
      const value = this.get(params.delegation_id); this.check(value,params.revision);
      if (value.status !== 'ready' || !value.expires_at || value.expires_at <= this.clock()) throw Error('委托尚未就绪或授权已到期');
      if (value.active_run_id || value.spec.kind === 'reminder') throw Error('委托已有运行，或应由提醒调度器处理');
      if (!version) throw Error('执行必须固定工作流版本');
      value.revision++; value.updated_at = this.clock();
      const run = DelegationRunSchema.parse({ id: randomUUID(),delegation_id: value.id,revision: value.revision,trigger_id: trigger,workflow_version: version,created_at: this.clock() });
      value.active_run_id = run.id; value.status = 'running'; value.reason = '已领取执行'; this.write(value);
      this.store.run('INSERT INTO delegation_run VALUES(?,?,?,NULL,?)',run.id,value.id,trigger,JSON.stringify(run));
      this.remember(trigger,fingerprint,run); return { run,created: true };
    });
  }
  run(id: string): DelegationRun {
    const row = this.store.connection.prepare('SELECT body FROM delegation_run WHERE id=?').get(id);
    if (!row) throw Error('执行不存在'); return DelegationRunSchema.parse(parseStoredJson(String(row.body)));
  }
  replayedRun(trigger: string, params: DelegationChange): DelegationRun | undefined {
    const previous = this.replay(trigger,'run:' + delegationJson(params)); return previous ? this.run(DelegationRunSchema.parse(previous).id) : undefined;
  }
  bind(id: string, turnId: string): void {
    this.store.transaction(() => this.bindWithinTransaction(id,turnId));
  }
  bindWithinTransaction(id: string, turnId: string): void {
      const run = this.run(id); if (run.turn_id && run.turn_id !== turnId) throw Error('执行已关联另一轮任务');
      if (!this.active(id)) throw Error('委托执行权已失效');
      run.turn_id = turnId; run.status = 'running'; this.store.run('UPDATE delegation_run SET turn_id=?,body=? WHERE id=?',turnId,JSON.stringify(run),id);
  }
  active(id: string): boolean {
    const run = this.run(id), value = this.get(run.delegation_id);
    return ['reserved','running'].includes(run.status) && value.status === 'running' && value.revision === run.revision &&
      value.active_run_id === id && value.expires_at !== null && this.clock() < value.expires_at;
  }
  recordCompletion(run: DelegationRun): void {
    if (run.status === 'completed' && run.verdict === 'verified' && run.finished_at !== null) {
      this.store.run('INSERT OR IGNORE INTO delegation_event VALUES(?,?,?,?)',`completed-run-${run.id}`,'delegation_completed',run.delegation_id,run.finished_at);
    }
  }
  settle(turnId: string, status: DelegationRun['status'], verdict: DelegationRun['verdict'], reason: string): void {
    this.store.transaction(() => this.settleWithinTransaction(turnId,status,verdict,reason));
  }
  settleWithinTransaction(turnId: string, status: DelegationRun['status'], verdict: DelegationRun['verdict'], reason: string): void {
      const row = this.store.connection.prepare('SELECT body FROM delegation_run WHERE turn_id=?').get(turnId); if (!row) return;
      const run = DelegationRunSchema.parse(parseStoredJson(String(row.body))); if (!['reserved','running'].includes(run.status)) return;
      Object.assign(run,{ status,verdict,reason,finished_at: this.clock() });
      this.store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(run),run.id);
      const value = this.get(run.delegation_id); if (value.revision !== run.revision || value.status !== 'running') return;
      value.status = status === 'completed' && verdict === 'verified' ? 'completed' : status === 'failed' || verdict === 'failed' ? 'failed' : 'needs_review';
      value.reason = reason; if (['completed','failed'].includes(value.status)) value.active_run_id = '';
      value.revision++; value.updated_at = this.clock(); this.write(value); if (value.status === 'completed') this.recordCompletion(run);
  }
  recover(id: string | null = null): void {
    this.store.transaction(() => {
      for (const row of this.store.connection.prepare('SELECT body FROM delegation_run WHERE ? IS NULL OR id=?').all(id,id)) {
        const run = DelegationRunSchema.parse(parseStoredJson(String(row.body)));
        if (run.workflow_version === 'notification' || !['reserved','running'].includes(run.status)) continue;
        run.status = 'interrupted'; run.verdict = 'unknown'; run.reason = '服务中断，尚未核实结果；不自动重放'; run.finished_at = this.clock();
        this.store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(run),run.id);
        const value = this.get(run.delegation_id); if (['paused','cancelled'].includes(value.status)) continue;
        value.status = 'needs_review'; value.reason = run.reason; value.revision++; value.updated_at = this.clock(); this.write(value);
      }
    });
  }
  review(id: string, reason: string): void {
    this.store.transaction(() => {
      const value = this.get(id); if (['completed','cancelled','failed','paused','draft'].includes(value.status)) return;
      value.status = 'needs_review'; value.reason = reason; value.revision++; value.updated_at = this.clock(); this.write(value);
    });
  }
}
