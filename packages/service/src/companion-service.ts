import { join } from 'node:path';
import { type RuntimeSettings, type TurnState } from '@lobuddy/contracts';
import { FocusTimer, casefold } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { KnowledgeService } from './knowledge/service.js';
import { ProjectService } from './knowledge/projects.js';
import { projectHandlers } from './knowledge/project-handlers.js';
import { LearningService } from './knowledge/learning.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { Companionship, proactiveInstruction } from './companion/policy.js';
import { CompanionAppearance } from './companion/appearance.js';
import { ThemeService } from './companion/themes.js';
import { memoryExpired } from './companion/topics.js';
import { TaskCoordinator } from './tasks/coordinator.js';
import { ImageStore } from './tools/images.js';
import type { Handlers } from './rpc-server.js';

export async function createCompanionServices(store: Store, settings: () => RuntimeSettings, images: ImageStore,
  knowledge: KnowledgeService, tasks: TaskCoordinator) {
  const lifetime = new AbortController(), companionship = new Companionship(store);
  const projects = new ProjectService(store,knowledge.relationship,lifetime.signal);
  const learning = new LearningService(store,() => tasks.busy);
  let analysisSignal: AbortSignal | undefined;
  const analyze = (prompt: string, signal: AbortSignal) => learning.analyze(prompt,signal,(p,s,max) => tasks.analyze(p,s,max));
  const dialogue = new CompanionDialogue(store,companionship,knowledge.relationship,projects,{
    enabled: () => learning.policy.enabled, quiet: () => tasks.busy,
    canReserve: (input,output) => learning.repo.canReserve(learning.clock(),learning.policy,{ calls: 1,input_tokens: input,output_tokens: output }),
    enqueue: (kind,source) => learning.enqueue(kind,source),
    analyze: prompt => {
      if (!analysisSignal) throw Error('话题调用未取得后台执行权'); return analyze(prompt,analysisSignal);
    },
  });
  knowledge.projectContext = state => projects.context(state); knowledge.dialogueContext = state => dialogue.context(state);
  knowledge.relationship.onInvalidate = () => {
    dialogue.clear();
    // New runs receive fresh engine sessions; history remains an audit record, not context authority.
    store.run('DELETE FROM engine_session');
  };
  knowledge.relationship.recover(); knowledge.bootstrap();
  learning.handlers.set('relationship',{ calls: 1,input_tokens: 8192,output_tokens: 1024,run: async (source,signal) => {
    const message = knowledge.relationship.sources([source])[0];
    if (!message) return { skipped: 'forgotten_source' };
    return knowledge.relationship.analyze(message.session_id,prompt => analyze(prompt,signal));
  } });
  learning.handlers.set('companion_topic',{ calls: 1,input_tokens: 8192,output_tokens: 1024,run: async (source,signal) => {
    analysisSignal = signal; try { return await dialogue.prepare(source); } finally { analysisSignal = undefined; }
  } });
  learning.handlers.set('maintenance',{ calls: 0,input_tokens: 0,output_tokens: 0,run: async (_source,signal) => {
    let expired = 0, duplicates = 0; const seen = new Set<string>(), profiles = new Map<string,Set<string>>();
    for (const item of knowledge.repo.list(undefined,'active',undefined,10000)) {
      signal.throwIfAborted(); if (!settings().memory_lint_enabled) break;
      expired += Number(memoryExpired(item)); const key = `${item.memory_type}:${casefold(item.content.trim())}`;
      duplicates += Number(seen.has(key)); seen.add(key);
      if (['user_profile','system_profile'].includes(item.memory_type) && item.title) {
        const key = `${item.memory_type}:${item.title}`, values = profiles.get(key) ?? new Set<string>(); values.add(item.content); profiles.set(key,values);
      }
    }
    const stale = knowledge.activeSkills().filter(skill => new Date(skill.last_used_at ?? skill.created_at).getTime() < Date.now() - settings().skill_stale_review_days * 86400000).length;
    return { expired_memories: expired,duplicate_memories: duplicates,possible_conflicts: [...profiles.values()].filter(values => values.size > 1).length,stale_skills: stale,read_only: true };
  } });
  learning.consumers = () => [
    { setting: 'relationship_enabled',enabled: knowledge.relationship.enabled && learning.policy.enabled,consumer: 'relationship',behavior: '有来源的相处学习与语义摘要；前台优先，按日预算限制' },
    { setting: 'learning.enabled（陪伴话题）',enabled: learning.policy.enabled,consumer: 'companion_topic',behavior: '只依据已授权来源组合短句，共享调用和 token 上限' },
    { setting: 'memory_lint_enabled',enabled: settings().memory_lint_enabled && learning.policy.enabled,consumer: 'maintenance',behavior: '每日只读巡检，不自动删除资料' },
    { setting: 'memory_profile_daily_consolidation',enabled: false,consumer: '未接入',behavior: '独立画像整理未启用；不以配置值冒充运行' },
  ];
  const appearance = new CompanionAppearance(store,settings().data_dir); await appearance.initialize();
  const themes = new ThemeService(store,appearance,images,join(settings().data_dir,'images'));
  const focus = new FocusTimer(settings,session => {
    knowledge.recordFocus(session.id,session.minutes); companionship.trigger({ event: 'focus_finished' });
  });
  let timer: ReturnType<typeof setInterval> | undefined;
  const start = () => {
    learning.start(); if (timer) return;
    timer = setInterval(() => {
      try { focus.poll(); dialogue.enqueue(); } catch { if (timer) clearInterval(timer); timer = undefined; }
    },1000); timer.unref();
  };
  const beforeStart = (state: TurnState) => {
    if (learning.policy.enabled) knowledge.relationship.immediate(state.session_id,state.turn_id,state.input_text);
    companionship.respond(state.input_text); dialogue.respond(state);
    const instruction = proactiveInstruction(state.input_text);
    if (instruction !== undefined) companionship.configure({ ...companionship.policy,enabled: instruction });
  };
  const settled = (state: TurnState) => {
    if (state.status === 'completed') {
      learning.enqueue('relationship',state.turn_id); companionship.trigger({ event: 'conversation_finished' });
    }
  };
  const handlers: Handlers = { ...knowledge.handlers(), ...projectHandlers(projects,tasks),
    'learning.get': () => learning.view(), 'learning.configure': p => learning.configure(p),
    'dialogue.get': p => ({ state: dialogue.state(p.session_id) ?? null, boundaries: dialogue.boundaries() }),
    'dialogue.boundary.remove': p => { dialogue.release(p.boundary_id); return { changed: true }; },
    'companionship.source': p => ({ label: dialogue.label(p.source_id),reason: '来自你明确保存的相处记录；不是读取屏幕或其他应用' }),
    'companionship.overview': () => companionship.topics.overview(), 'companionship.topics': () => companionship.topics.list(),
    'companionship.topic.unblock': p => { companionship.topics.feedback(p.topic_id,'unblock'); return { changed: true }; },
    'companionship.get': () => companionship.policy, 'companionship.configure': p => companionship.configure(p),
    'companionship.activity': async p => { if (p.typing || p.conversation) await learning.activity(); companionship.engage(p); return { accepted: true }; },
    'companionship.trigger': p => { companionship.trigger(p); dialogue.enqueue(); return { accepted: true }; },
    'companionship.feedback': p => { companionship.feedback(p); return { accepted: true }; },
    'companionship.poll': () => companionship.poll(focus.active,tasks.busy || tasks.approvals.list().length > 0),
    'companion.get': () => appearance.value, 'companion.save': p => appearance.save(p), 'companion.import': p => appearance.importImage(p.path),
    'theme.list': () => themes.list(), 'theme.save': p => themes.save(p),
    'theme.apply': async p => { await themes.apply(p.theme_id); return { applied: true }; },
    'theme.delete': p => ({ deleted: themes.remove(p.theme_id) }), 'theme.from_image': p => themes.fromImage(p.image_id),
    'focus.get': () => focus.view(), 'focus.start': p => { focus.start(p.minutes); return focus.view(); },
    'focus.pause': () => { focus.pause(); return focus.view(); }, 'focus.resume': () => { focus.resume(); return focus.view(); },
    'focus.stop': () => { focus.stop(); return focus.view(); },
  };
  // Ensure user edits preempt background derivation, and update running contexts after the write.
  const mutate = ['memory.save','memory.delete','preference.save','relationship.edit','relationship.resolve','relationship.forget','relationship.configure'];
  for (const method of Object.keys(handlers) as (keyof Handlers)[]) {
    const handler = handlers[method]!;
    const wrapped = async (params: never, context: never) => {
      start(); if (mutate.includes(method) || method.startsWith('project.') || method.startsWith('source.')) await learning.activity();
      const result = await (handler as (p: never,c: never) => unknown)(params,context);
      if (mutate.includes(method)) {
        // A request already sent to a provider cannot be retracted by changing a local projection.
        for (const state of tasks.activeStates()) if (state.lane === 'foreground') await tasks.cancel(state.turn_id);
      }
      return result;
    };
    Object.assign(handlers,{ [method]: wrapped });
  }
  return { handlers, learning, dialogue, companionship, projects, focus, appearance, themes, beforeStart, settled, start,
    close: async () => { lifetime.abort(); if (timer) clearInterval(timer); focus.stop(); await learning.close(); } };
}
