import { createHash } from 'node:crypto';
import { DelegationViewSchema, type SourceView } from '@lobuddy/contracts';
import type { Handlers } from '../rpc-server.js';
import type { TaskCoordinator } from '../tasks/coordinator.js';
import { parseStoredJson } from '../storage/json.js';
import { ProjectService } from './projects.js';
export function projectHandlers(projects: ProjectService, tasks: TaskCoordinator): Handlers {
  const repo = projects.repo;
  const current = (id: string, revision: number) => {
    const value = repo.source(id);
    if (value.revision !== revision || value.status === 'forgotten') throw Error('来源已更新或已遗忘，请刷新'); return value;
  };
  const cancelUsed = async (value: SourceView) => {
    const sessions = new Set(repo.sourceSessions(value.id));
    for (const state of tasks.activeStates()) if (sessions.has(state.session_id)) await tasks.cancel(state.turn_id);
  };
  return {
    'project.list': () => repo.projects(),
    'project.create': (p,c) => { projects.clean(p.name + p.goal,false); return repo.create(c.requestId,p); },
    'project.get': p => ({ project: repo.project(p.project_id), sources: repo.sources().filter(s => s.project_id === p.project_id).map(s => projects.fresh(s)),
      delegations: projects.store.connection.prepare('SELECT body FROM delegation ORDER BY rowid DESC').all()
        .map(row => DelegationViewSchema.parse(parseStoredJson(String(row.body)))).filter(d => d.spec.project_id === p.project_id) }),
    'project.edit': p => {
      projects.clean(p.name + p.goal,false);
      if (tasks.activeStates().some(state => state.project_id === p.project_id)) throw Error('请等待当前项目对话结束或先取消，再修改项目');
      const value = repo.saveProject({ ...repo.project(p.project_id), name: p.name, goal: p.goal, status: p.status },p.revision);
      repo.resetEngines(repo.projectSessions(p.project_id)); repo.clearDerived(p.project_id); projects.relationship.invalidate(); return value;
    },
    'project.selection': p => repo.selection(p.session_id),
    'project.bind': p => {
      if (p.project_id) repo.project(p.project_id);
      if (tasks.activeStates().some(state => state.session_id === p.session_id)) throw Error('请等待当前对话结束或先取消，再切换项目');
      repo.bind(p.session_id,p.project_id,p.revision); repo.resetEngines([p.session_id]); projects.relationship.invalidate();
      return { project_id: p.project_id, revision: p.revision + 1 };
    },
    'source.list': () => repo.sources().map(value => projects.fresh(value)),
    'source.share': (p,c) => { if (p.kind === 'file') throw Error('文件必须由原生选择器导入'); return projects.share(c.requestId,p); },
    'source.import_file': (p,c) => { if (p.kind !== 'file') throw Error('请选择本地文件'); return projects.share(c.requestId,p); },
    'source.forget': async p => {
      const value = projects.forget(current(p.source_id,p.revision)); await cancelUsed(value); return value;
    },
    'source.correct': async p => {
      const value = current(p.source_id,p.revision);
      const sensitive = projects.clean(p.text,p.sensitive_confirmed);
      if (value.kind !== 'text') throw Error('文件或链接请重新分享；不伪造原文');
      const result = repo.saveSource({ ...value, text: p.text, sha256: createHash('sha256').update(p.text).digest('hex'), sensitive, source_message_id: '' },p.revision);
      projects.invalidate(result); await cancelUsed(result); return result;
    },
    'source.move': async p => {
      const value = current(p.source_id,p.revision); projects.scope(p.project_id,p.session_id); projects.invalidate(value);
      const result = repo.saveSource({ ...value, project_id: p.project_id, session_id: p.session_id,
        expires_at: p.session_id ? Math.min(value.expires_at ?? projects.clock() + 86400,projects.clock() + 86400) : value.expires_at },p.revision);
      projects.invalidate(result); await cancelUsed(result); return result;
    },
  };
}
