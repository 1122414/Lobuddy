import { join } from 'node:path';
import { type RuntimeSettings, type TurnState } from '@lobuddy/contracts';
import { FocusTimer, casefold } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { KnowledgeService } from './knowledge/service.js';
import { ProjectService } from './knowledge/projects.js';
import { projectHandlers } from './knowledge/project-handlers.js';
import { LearningService } from './knowledge/learning.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { CompanionHandoffs } from './companion/handoff.js';
import { CareService } from './companion/care.js';
import { INVITATION_BUDGET } from './companion/invitations.js';
import { Companionship, proactiveInstruction } from './companion/policy.js';
import { CompanionAppearance } from './companion/appearance.js';
import { ThemeService } from './companion/themes.js';
import { memoryExpired } from './companion/topics.js';
import { TaskCoordinator } from './tasks/coordinator.js';
import { ImageStore } from './tools/images.js';
import type { Handlers } from './rpc-server.js';
import { WorkflowEvolution } from './knowledge/evolution.js';
import { learnSkill } from './knowledge/skill-learning.js';

export async function createCompanionServices(store: Store, settings: () => RuntimeSettings, images: ImageStore,
  knowledge: KnowledgeService, tasks: TaskCoordinator, focusFinished: (id: string) => void = () => {},voiceActive: () => boolean = () => false) {
  const lifetime = new AbortController(), companionship = new Companionship(store);
  const projects = new ProjectService(store,knowledge.relationship,lifetime.signal);
  const learning = new LearningService(store,() => tasks.busy || voiceActive());
  const evolution = new WorkflowEvolution(tasks.workflows);
  const skillContext = knowledge.skillContext;
  knowledge.skillContext = state => {
    const context = skillContext(state);
    return context ? tasks.workflows.context(JSON.parse(context) as Record<string,unknown>,state.turn_id) : tasks.workflows.context({ skills: [] },state.turn_id);
  };
  const forget = knowledge.relationship.onForget;
  knowledge.relationship.onForget = sources => { forget?.(sources); evolution.forget(sources); };
  let analysisSignal: AbortSignal | undefined;
  const analyze = (prompt: string, signal: AbortSignal) => learning.analyze(prompt,signal,(p,s,max) => tasks.analyze(p,s,max));
  const dialogue = new CompanionDialogue(store,companionship,knowledge.relationship,projects,{
    enabled: () => learning.policy.enabled, quiet: () => tasks.busy || voiceActive() || focus.active,
    canReserve: (input,output,calls = 1) => learning.repo.canReserve(learning.clock(),learning.policy,{ calls,input_tokens: input,output_tokens: output }),
    enqueue: (kind,source) => learning.enqueue(kind,source),
    analyze: prompt => {
      if (!analysisSignal) throw Error('话题调用未取得后台执行权');
      return learning.analyze(prompt,analysisSignal,(p,s,max) => tasks.analyze(p,s,max,'off'));
    },
  });
  const handoffs = new CompanionHandoffs(dialogue, session => tasks.activeStates().some(state => state.session_id === session), turns => {
    // cancel marks the turn and aborts tool authority synchronously, then waits for engine acknowledgement.
    for (const state of tasks.activeStates()) if (turns.includes(state.turn_id)) void tasks.cancel(state.turn_id).catch(() => {});
  });
  const care = new CareService(store,knowledge,projects);
  care.onChange = () => { dialogue.clear(); handoffs.reconcile(); };
  knowledge.relationship.onCare = (items,session) => { for (const item of items) care.admit(item,session); };
  knowledge.gateway.onChange = () => { care.reconcile(); handoffs.reconcile(); };
  knowledge.projectContext = state => projects.context(state);
  knowledge.dialogueContext = state => handoffs.context(state) + dialogue.context(state);
  knowledge.relationship.onInvalidate = () => {
    dialogue.clear();
    // New runs receive fresh engine sessions; history remains an audit record, not context authority.
    store.run('DELETE FROM engine_session');
    handoffs.reconcile();
    care.reconcile();
  };
  handoffs.reconcile(); knowledge.relationship.recover(); knowledge.bootstrap();
  learning.handlers.set('relationship',{ calls: 1,input_tokens: 8192,output_tokens: 1024,run: async (source,signal) => {
    if (!knowledge.relationship.enabled) return { skipped: 'relationship_disabled' };
    const message = knowledge.relationship.sources([source])[0];
    if (!message) return { skipped: 'forgotten_source' };
    return knowledge.relationship.analyze(message.session_id,prompt => analyze(prompt,signal));
  } });
  learning.handlers.set('companion_topic',{ ...INVITATION_BUDGET,releaseUnusedCalls: true,run: async (source,signal) => {
    analysisSignal = signal; try { return await dialogue.prepare(source); } finally { analysisSignal = undefined; }
  } });
  learning.handlers.set('skill_evidence',{ calls: 0,input_tokens: 0,output_tokens: 0,run: async (source,signal) => {
    signal.throwIfAborted(); return learnSkill(knowledge.skills,tasks.turns.get(source));
  } });
  learning.handlers.set('workflow_proposal',{ calls: 1,input_tokens: 8192,output_tokens: 2048,run: async (source,signal) => {
    const epoch = knowledge.relationship.epoch();
    const current = () => !signal.aborted && learning.policy.enabled && epoch === knowledge.relationship.epoch() && knowledge.relationship.sources([source]).length > 0;
    const result = await evolution.generate(source,(prompt,max) => learning.analyze(prompt,signal,(p,s,n) => tasks.analyze(p,s,n),max),signal,current);
    return result ? { version_id: result.version_id,status: result.status } : { skipped: 'no_verified_improvement_source' };
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
    { setting: 'learning.enabled（技能证据）',enabled: learning.policy.enabled,consumer: 'skill_evidence',behavior: '有证据的结果或明确纠正生成待审候选，不把技能读取计为成功' },
    { setting: 'learning.enabled（工作流提议）',enabled: learning.policy.enabled,consumer: 'workflow_proposal',behavior: '已验证轨迹触发有预算提议；固定隔离评测，不扩大权限' },
    { setting: 'relationship_enabled',enabled: knowledge.relationship.enabled && learning.policy.enabled,consumer: 'relationship',behavior: '有来源的相处学习与语义摘要；前台优先，按日预算限制' },
    { setting: 'learning.enabled（陪伴话题）',enabled: learning.policy.enabled,consumer: 'companion_topic',behavior: '比较有效话题，选择说/稍后/放弃；自然短句经独立审查，最多两次分析，共享日额度' },
    { setting: 'memory_lint_enabled',enabled: settings().memory_lint_enabled && learning.policy.enabled,consumer: 'maintenance',behavior: '每日只读巡检，不自动删除资料' },
    { setting: 'memory_profile_daily_consolidation',enabled: false,consumer: '未接入',behavior: '独立画像整理未启用；不以配置值冒充运行' },
  ];
  const appearance = new CompanionAppearance(store,settings().data_dir); await appearance.initialize();
  const themes = new ThemeService(store,appearance,images,join(settings().data_dir,'images'));
  const focus = new FocusTimer(settings,session => {
    knowledge.recordFocus(session.id,session.minutes); companionship.trigger({ event: 'focus_finished' });
    focusFinished(session.id);
  });
  let timer: ReturnType<typeof setInterval> | undefined;
  const start = () => {
    learning.start(); if (timer) return;
    timer = setInterval(() => {
      try { focus.poll(); handoffs.reconcile(); dialogue.enqueue(); } catch { if (timer) clearInterval(timer); timer = undefined; }
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
      if (knowledge.relationship.enabled) learning.enqueue('relationship',state.turn_id);
      companionship.trigger({ event: 'conversation_finished' });
    }
    const outcome = tasks.ledger.outcomes.get(state.turn_id);
    if (['verified','failed'].includes(outcome.verdict) || /^(?:以后|下次)(?:整理|归纳)/u.test(state.input_text)) {
      learning.enqueue('skill_evidence',state.turn_id);
      if (outcome.verdict === 'verified') learning.enqueue('workflow_proposal',state.turn_id);
    }
  };
  const handlers: Handlers = { ...knowledge.handlers(), ...projectHandlers(projects,tasks),
    'care.get': () => care.view(),
    'care.configure': (p,c) => care.configure(p,c.requestId),
    'care.update': (p,c) => care.update(p,c.requestId),
    'care.preset': async () => {
      companionship.configure({ ...companionship.policy,daily_limit: 5,interval_minutes: 60 });
      await learning.configure({ ...learning.policy,daily_calls: 40,daily_input_tokens: 160000,daily_output_tokens: 20000 });
      return care.configure({ ...care.policy,enabled: true,start_hour: 9,end_hour: 23 });
    },
    'session.history': p => new ChatRepository(store).messages(p.session_id),
    'workflow.list': () => tasks.workflows.versions(),
    'workflow.propose': (p,c) => evolution.propose(p.definition,p.reason,[c.requestId]),
    'workflow.evaluate': async (p,c) => { const epoch = knowledge.relationship.epoch(); return evolution.evaluate(p.version_id,AbortSignal.any([c.signal,lifetime.signal]),() => epoch === knowledge.relationship.epoch()); },
    'workflow.enable': p => { tasks.workflows.enable(p.version_id); return { changed: true }; },
    'workflow.disable': p => { tasks.workflows.disable(p.version_id); return { changed: true }; },
    'workflow.rollback': p => { tasks.workflows.rollback(p.version_id); return { changed: true }; },
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
    'companionship.accept': p => handoffs.accept(p.notice_id,p.session_id),
    'companionship.poll': () => companionship.poll(focus.active,tasks.busy || voiceActive() || tasks.approvals.list().length > 0),
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
  const skillMutations = ['skill.save','skill.toggle','skill.archive','skill.candidate.resolve'];
  const preempt = new Set([...mutate,...skillMutations,'project.create','project.edit','project.bind','source.share','source.import_file','source.forget','source.correct','source.move',
    'workflow.propose','workflow.evaluate','workflow.enable','workflow.disable','workflow.rollback']);
  for (const method of Object.keys(handlers) as (keyof Handlers)[]) {
    const handler = handlers[method]!;
    const wrapped = async (params: never, context: never) => {
      start(); handoffs.reconcile(); if (preempt.has(method)) await learning.activity();
      const result = await (handler as (p: never,c: never) => unknown)(params,context);
      handoffs.reconcile();
      if (skillMutations.includes(method)) knowledge.relationship.invalidate();
      if (mutate.includes(method)) {
        // A request already sent to a provider cannot be retracted by changing a local projection.
        for (const state of tasks.activeStates()) if (state.lane === 'foreground') await tasks.cancel(state.turn_id);
      }
      return result;
    };
    Object.assign(handlers,{ [method]: wrapped });
  }
  return { handlers, learning, dialogue, handoffs, companionship, projects, focus, appearance, themes, care, beforeStart, settled, start,
    close: async () => { lifetime.abort(); if (timer) clearInterval(timer); focus.stop(); await learning.close(); } };
}
