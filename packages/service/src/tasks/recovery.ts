import { createHash } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { z } from 'zod';
import { JsonRecordSchema, OutcomeSchema, type RecoveryRequest, type RuntimeSettings } from '@lobuddy/contracts';
import { WorkspaceFiles } from '../tools/files.js';
import { parseStoredJson } from '../storage/json.js';
import { TaskCoordinator } from './coordinator.js';
const Effects = z.array(z.strictObject({ source: z.string(),target: z.string(),sha256: z.string().regex(/^[a-f0-9]{64}$/) })).min(1).max(1000);
export class DelegationRecovery {
  constructor(readonly tasks: TaskCoordinator,readonly settings: () => RuntimeSettings) {}
  recover(params: RecoveryRequest): void {
    const repo = this.tasks.delegations, value = repo.get(params.delegation_id);
    if (value.revision !== params.revision || !['paused','needs_review'].includes(value.status)) throw Error('请重新读取需要核对的委托');
    const run = repo.detail(value.id).runs.find(run => run.id === value.active_run_id);
    if (!run?.turn_id || ['reserved','running'].includes(run.status)) throw Error('执行尚未停止或没有可核对记录');
    const settings = this.settings(),files = new WorkspaceFiles(settings.workspace_path,[settings.data_dir]);
    const digest = (path: string,limit = 100000) => createHash('sha256').update(files.readBytes(path,limit)).digest('hex');
    const store = repo.store;
    if (value.spec.kind === 'organize-files') {
      if (params.action !== 'inspect') throw Error('未知写操作不得重放');
      const rows = store.connection.prepare('SELECT body FROM task_effect WHERE turn_id=?').all(run.turn_id);
      if (!rows.length) throw Error('没有写入证据，请核对后新建委托');
      const evidence = rows.flatMap(row => Effects.parse(parseStoredJson(String(row.body))));
      for (const entry of evidence) if (digest(entry.source,5000000) !== entry.sha256 || digest(entry.target,5000000) !== entry.sha256) throw Error('产物不符，保留未知状态，不重做写入');
      const outcome = OutcomeSchema.parse({ turn_id: run.turn_id,verdict: 'verified',scenario: 'organize',criteria: ['原文件与全部副本 SHA-256 一致'],evidence,reason: '已逐一核对原文件和副本；没有重新执行写入' });
      store.transaction(() => {
        if (repo.get(value.id).revision !== params.revision) throw Error('委托已变化');
        this.tasks.ledger.outcomes.save(outcome);
        Object.assign(run,{ status: 'completed',verdict: 'verified',reason: outcome.reason,finished_at: repo.clock() });
        store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(run),run.id);
        value.status = 'completed'; value.reason = outcome.reason; value.active_run_id = ''; value.revision++; value.updated_at = repo.clock(); repo.write(value); repo.recordCompletion(run);
      }); return;
    }
    if (value.spec.kind !== 'source-digest') throw Error('该委托不支持只读检查点恢复');
    const snapshot = store.connection.prepare('SELECT * FROM delegation_checkpoint WHERE run_id=?').get(run.id);
    if (value.spec.sources.some(source => /^https?:\/\//.test(source))) throw Error('网络来源无法保证版本一致');
    const sources = Object.fromEntries(value.spec.sources.map(source => [source,digest(source)]));
    if (!snapshot || !isDeepStrictEqual(parseStoredJson(String(snapshot.sources)),sources)) throw Error('来源已变化，不能恢复旧检查点');
    if (snapshot.version !== run.workflow_version || !this.tasks.workflows.get(run.workflow_version).active) throw Error('原工作流版本已变化或停用');
    const values = JsonRecordSchema.parse(parseStoredJson(String(snapshot.body)));
    const definition = this.tasks.workflows.get(run.workflow_version).definition;
    // A checkpoint is an execution prefix, never permission to skip a model or write step.
    const completed = Object.keys(values).filter(key => key !== 'input');
    if (completed.length > definition.nodes.length || definition.nodes.slice(0,completed.length).some(node =>
      !completed.includes(node.id) || ['model','output'].includes(node.kind) || node.tool === 'lobuddy_organize')) throw Error('检查点不是可恢复的只读步骤');
    if (!isDeepStrictEqual(values.input,this.tasks.turns.get(run.turn_id).workflow_input)) throw Error('检查点输入不符');
    if (params.action === 'inspect') return;
    if (!value.expires_at || value.expires_at <= repo.clock()) throw Error('授权已到期');
    this.tasks.resumeReadonly(run.turn_id,() => {
      if (repo.get(value.id).revision !== params.revision) throw Error('委托已更新');
      value.revision++; value.updated_at = repo.clock(); value.status = 'running'; value.reason = '来源版本一致，从只读检查点继续';
      run.revision = value.revision; run.status = 'running'; run.finished_at = null; repo.write(value);
      store.run('UPDATE delegation_run SET body=? WHERE id=?',JSON.stringify(run),run.id);
    });
  }
}
