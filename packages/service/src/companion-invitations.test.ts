import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { ChatSessionSchema, MemoryItemSchema, ProjectCreateSchema, SourceShareSchema, LearningPolicySchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { ChatRepository } from './storage/chat.js';
import { runtimeSettings } from './config/settings.js';
import { KnowledgeService } from './knowledge/service.js';
import { ProjectService } from './knowledge/projects.js';
import { LearningService } from './knowledge/learning.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { Companionship } from './companion/policy.js';
import { INVITATION_BUDGET, naturalInvitation } from './companion/invitations.js';
import { setImmediate as tick } from 'node:timers/promises';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-invitations-')), data = join(root,'data'), workspace = join(root,'workspace'); await mkdir(workspace);
  const store = new Store(join(data,'lobuddy.db'),{ create: true });
  const settings = runtimeSettings({ data,workspace,logs: join(root,'logs') });
  const knowledge = new KnowledgeService(store,() => settings);
  new ChatRepository(store).saveSession(ChatSessionSchema.parse({ id: 'current' }));
  let now = Date.now() / 1000, quiet = false, enabled = true;
  const companion = new Companionship(store,() => now), jobs: string[] = [], prompts: string[] = [];
  const projects = new ProjectService(store,knowledge.relationship,new AbortController().signal,() => now);
  let answer: (prompt: string) => Promise<string> = async () => JSON.stringify({ action: 'pass',reason: 'low_value' });
  const learning = { enabled: () => enabled,quiet: () => quiet,canReserve: () => true,
    enqueue: (_kind: string,id: string) => { jobs.push(id); }, analyze: async (prompt: string) => { prompts.push(prompt); return answer(prompt); } };
  const dialogue = new CompanionDialogue(store,companion,knowledge.relationship,projects,learning,() => now);
  knowledge.relationship.onInvalidate = () => dialogue.clear();
  const memory = (id: string,content: string,extra = {}) => knowledge.gateway.saveManual(MemoryItemSchema.parse({ id, memory_type: 'episodic_memory',title: id,content,...extra }));
  const project = projects.repo.create('project',ProjectCreateSchema.parse({ name: '星桥项目' }));
  const source = (text: string,title = '星桥近况') => projects.share(crypto.randomUUID(),SourceShareSchema.parse({ project_id: project.id,category: 'pending',title,text }));
  const trigger = (event: 'app_returned' | 'conversation_finished' = 'app_returned') => { companion.trigger({ event }); dialogue.enqueue(); };
  const reset = () => { dialogue.clear(); companion.state.pending = ''; companion.state.cooldown_until = 0; };
  const speak = (source_id: string,quote: string,text = `想到${quote}，还挺有意思的。`) => {
    answer = async prompt => JSON.stringify(prompt.startsWith('独立审查') ? { grounded: true,natural: true,respectful: true } : { action: 'speak',source_id,quote,text });
  };
  return { root,store,knowledge,companion,projects,dialogue,jobs,prompts,memory,source,trigger,reset,speak,learning,
    now: () => now,advance: (seconds: number) => { now += seconds; },quiet: (value: boolean) => { quiet = value; },enabled: (value: boolean) => { enabled = value; },
    answer: (fn: typeof answer) => { answer = fn; }, prepare: () => dialogue.prepare(jobs.at(-1)!),
    close: async () => { store.close(); await rm(root,{ recursive: true,force: true }); } };
}

test('candidate pool interleaves projects and memories, deduplicates text and keeps distinct same-version project sources', async () => {
  const f = await fixture();
  try {
    const sources: Awaited<ReturnType<typeof f.source>>[] = [];
    for (let n = 0; n < 5; n++) { f.advance(1); sources.push(await f.source(`星桥第${n}个方向还可以继续想想`)); f.memory(`memory${n}`,`我们一起试过第${n}种冷泡白茶`); }
    f.memory('duplicate',sources[4]!.text);
    const pool = f.dialogue.invitations.candidates(); assert.equal(pool.length,6);
    assert.equal(pool.filter(item => item.source_id.startsWith('project:')).length,3);
    assert.equal(new Set(pool.map(item => item.material)).size,pool.length);
    const shown = f.dialogue.source(`project:${sources[4]!.id}`)!;
    f.companion.topics.shown({ topic_id: shown.topic,memory_id: `project:${sources[4]!.id}`,revision: shown.revision,text: '' });
    assert.ok(f.dialogue.invitations.candidates().some(item => item.source_id === `project:${sources[3]!.id}`));
    f.store.run("INSERT INTO companion_topic VALUES(?,?,?,?,?,?)",`project:${sources[4]!.project_id}:pending`,`project:${sources[4]!.id}`,'1',f.now(),0,1);
    assert.equal(f.dialogue.invitations.candidates().filter(item => item.source_id.startsWith('project:')).length,0,'historical explicit project/category block remains effective');
  } finally { await f.close(); }
});

test('selector can choose a later candidate and the independent review sees only that source', async () => {
  const f = await fixture();
  try {
    await f.source('星桥专属资料标记甲，还没决定颜色'); f.memory('tea','一起试过冷泡白茶');
    f.speak('tea','冷泡白茶','想到冷泡白茶，感觉夏天又近了一点。'); f.trigger();
    assert.equal((await f.prepare()).prepared,true);
    assert.equal(f.prompts.length,2); assert.match(f.prompts[0]!,/专属资料标记甲/); assert.doesNotMatch(f.prompts[1]!,/专属资料标记甲/);
    f.advance(31); const notice = f.companion.poll(false,false)!;
    assert.equal(notice.memory_id,'tea'); assert.equal(notice.text,'想到冷泡白茶，感觉夏天又近了一点。');
    assert.equal(f.companion.state.used,1); assert.equal(f.companion.poll(false,false)?.notice_id,notice.notice_id);
  } finally { await f.close(); }
});

test('empty, low-value, repeated and blocked pools remain silent without spending display quota', async () => {
  const f = await fixture();
  try {
    f.trigger(); f.advance(31); assert.equal(f.companion.poll(false,false),null); assert.equal(f.jobs.length,0); assert.equal(f.companion.state.used,0);
    f.memory('tea','我们试过冷泡白茶'); f.trigger(); assert.equal((await f.prepare()).decision,'pass');
    f.advance(31); assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.used,0); assert.equal(f.prompts.length,1);
    const material = f.dialogue.source('tea')!;
    f.companion.topics.shown({ topic_id: material.topic,memory_id: 'tea',revision: material.revision,text: '' });
    f.trigger(); f.advance(31); assert.equal(f.companion.poll(false,false),null); assert.equal(f.jobs.length,1);
    f.advance(8 * 86400); f.companion.topics.feedback(material.topic,'never'); f.trigger(); f.advance(31);
    assert.equal(f.companion.poll(false,false),null); assert.equal(f.jobs.length,1);
  } finally { await f.close(); }
});

test('long Chinese candidate pools fit the actual governed bridge byte cap before invocation', async () => {
  const f = await fixture();
  try {
    for (let n = 0; n < 6; n++) await f.source(`第${n}段近况：${'记录今天读到的故事，'.repeat(55)}`);
    f.trigger(); await f.prepare();
    assert.equal(f.prompts.length,1);
    assert.ok(Buffer.byteLength(f.prompts[0]!) <= 7000);
    const materials = JSON.parse(f.prompts[0]!.slice(f.prompts[0]!.lastIndexOf('\n') + 1));
    assert.ok(materials.candidates.length >= 1 && materials.candidates.length < 6);
  } finally { await f.close(); }
});

test('defer waits five minutes, re-evaluates once and a second defer becomes a silent pass', async () => {
  const f = await fixture();
  try {
    f.memory('tea','一起试过冷泡白茶'); f.answer(async () => JSON.stringify({ action: 'defer',reason: 'too_soon' }));
    f.trigger('conversation_finished'); assert.equal((await f.prepare()).decision,'defer'); f.advance(31);
    assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.used,0);
    f.advance(268); f.dialogue.enqueue(); assert.equal(f.jobs.length,1);
    f.advance(1); f.dialogue.enqueue(); assert.equal(f.jobs.length,2); assert.notEqual(f.jobs[0],f.jobs[1]);
    await f.prepare(); assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.pending,'');
    f.advance(400); f.dialogue.enqueue(); assert.equal(f.jobs.length,2); assert.equal(f.companion.state.used,0);
  } finally { await f.close(); }
});

test('activity after preparation retires the ready text and permits only a fresh delayed evaluation', async () => {
  const f = await fixture();
  try {
    f.memory('tea','一起试过冷泡白茶'); f.speak('tea','冷泡白茶'); f.trigger(); await f.prepare();
    f.companion.engage({ client: 'quick',typing: true,conversation: true }); f.advance(31);
    assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.used,0);
    f.advance(300); f.dialogue.enqueue(); assert.equal(f.jobs.length,2);
    assert.equal((await f.prepare()).prepared,true); assert.ok(f.companion.poll(false,false));
  } finally { await f.close(); }
});

test('a model cannot invent a timing veto after the app-return gate has already been satisfied', async () => {
  const f = await fixture();
  try {
    f.memory('tea','一起试过冷泡白茶'); f.answer(async () => JSON.stringify({ action: 'defer',reason: 'too_soon' }));
    f.trigger(); assert.equal((await f.prepare()).skipped,'invalid_defer'); f.advance(31);
    assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.pending,'');
    assert.doesNotMatch(f.prompts[0]!,/\{"action":"defer"/);
  } finally { await f.close(); }
});

test('foreground activity and source correction during an awaited model result cannot deliver late speech', async () => {
  for (const change of ['activity','source','disabled','quiet']) {
    const f = await fixture();
    try {
      f.memory('tea','一起试过冷泡白茶'); let release!: () => void;
      f.answer(async () => { await new Promise<void>(resolve => { release = resolve; }); return JSON.stringify({ action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '想到冷泡白茶，感觉夏天又近了一点。' }); });
      f.trigger(); const pending = f.prepare(); await Promise.resolve();
      if (change === 'activity') f.companion.engage({ client: 'quick',typing: true,conversation: false });
      if (change === 'source') { f.memory('tea','星桥完全不同的近况'); f.knowledge.relationship.invalidate(); }
      if (change === 'disabled') f.enabled(false);
      if (change === 'quiet') f.quiet(true);
      release(); assert.equal((await pending).prepared,undefined,change);
      f.advance(31); assert.equal(f.companion.poll(false,false),null,change); assert.equal(f.companion.state.used,0,change);
    } finally { await f.close(); }
  }
});

test('invalid identity, unsupported quote, internal details and rejected reviews never become speech', async () => {
  const cases = [
    { draft: '{broken', review: true, calls: 1 },
    { draft: { action: 'speak',source_id: 'invented',quote: '冷泡白茶',text: '冷泡白茶很好。' },review: true,calls: 1 },
    { draft: { action: 'speak',source_id: 'tea',quote: '我们去过台湾',text: '我们去过台湾，真不错。' },review: true,calls: 1 },
    { draft: { action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: 'source_id: tea；冷泡白茶很好。' },review: true,calls: 1 },
    { draft: { action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '你已经喝了冷泡白茶。' },review: false,calls: 2 },
    { draft: { action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '冷泡白茶怎么还没试？' },review: false,calls: 2 },
  ];
  for (const value of cases) {
    const f = await fixture();
    try {
      f.memory('tea','以后想试试冷泡白茶，还没试过');
      f.answer(async prompt => prompt.startsWith('独立审查') ? JSON.stringify({ grounded: value.review,natural: value.review,respectful: value.review }) :
        typeof value.draft === 'string' ? value.draft : JSON.stringify(value.draft));
      f.trigger(); assert.equal((await f.prepare()).prepared,undefined); f.advance(31);
      assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.used,0); assert.equal(f.prompts.length,value.calls);
    } finally { await f.close(); }
  }
  assert.equal(naturalInvitation('冷泡白茶。一句话。再一句话。','冷泡白茶'),false);
  assert.equal(naturalInvitation('冷泡白茶试了吗？好喝吗？','冷泡白茶'),false);
});

test('source retirement during independent review cancels the prepared result', async () => {
  const f = await fixture();
  try {
    f.memory('tea','一起试过冷泡白茶'); let finish!: () => void;
    f.answer(async prompt => {
      if (!prompt.startsWith('独立审查')) return JSON.stringify({ action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '想起冷泡白茶，真有意思。' });
      await new Promise<void>(resolve => { finish = resolve; }); return JSON.stringify({ grounded: true,natural: true,respectful: true });
    });
    f.trigger(); const pending = f.prepare(); await tick(); assert.equal(f.prompts.length,2);
    f.knowledge.gateway.delete('tea'); finish(); assert.equal((await pending).prepared,undefined);
    f.advance(31); assert.equal(f.companion.poll(false,false),null);
  } finally { await f.close(); }
});

test('partly paraphrased proposed quotes keep only an exact shared fragment before independent review', async () => {
  const f = await fixture();
  try {
    f.memory('story','纸船故事还没写完，结尾尚未决定。');
    f.speak('story','纸船故事还没写完，结尾尚未决定','你那个纸船故事还没写完，结尾也还没定。');
    f.trigger(); assert.equal((await f.prepare()).prepared,true);
    const body = JSON.parse(String(f.store.connection.prepare('SELECT body FROM dialogue_invitation').get()!.body));
    const quote = [...f.dialogue.source('story')!.text].slice(body.start,body.start + body.length).join('');
    assert.ok(quote.length >= 4); assert.ok(body.text.includes(quote)); assert.equal(f.prompts.length,2);
    f.reset(); f.speak('story','纸船故事还没写完','另一件不相干的事。'); f.trigger();
    assert.equal((await f.prepare()).skipped,'invalid_source_or_quote');
    f.reset(); f.memory('story','周末用松果做了一只小刺猬，最有趣的是给它起名叫团团。');
    f.speak('story','最有趣的是给它起名叫团团','你周末用松果做的小刺猬叫团团，这名字挺可爱的。'); f.trigger();
    assert.equal((await f.prepare()).prepared,true);
  } finally { await f.close(); }
});

test('selection or review failure becomes a silent terminal decision without an automatic prose retry', async () => {
  for (const phase of ['selection','review']) {
    const f = await fixture();
    try {
      f.memory('tea','一起试过冷泡白茶');
      f.answer(async prompt => {
        if (phase === 'selection' || prompt.startsWith('独立审查')) throw Error('synthetic unavailable');
        return JSON.stringify({ action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '想起冷泡白茶，还挺有意思的。' });
      });
      f.trigger(); assert.equal((await f.prepare()).skipped,`${phase}_unavailable`);
      f.dialogue.enqueue(); assert.equal(f.jobs.length,1); f.advance(31);
      assert.equal(f.companion.poll(false,false),null); assert.equal(f.companion.state.used,0);
    } finally { await f.close(); }
  }
});

test('ready v2 drafts are not replayed by a new service owner', async () => {
  const f = await fixture();
  try {
    f.memory('tea','一起试过冷泡白茶'); f.speak('tea','冷泡白茶'); f.trigger(); await f.prepare();
    const next = new CompanionDialogue(f.store,f.companion,f.knowledge.relationship,f.projects,f.learning,f.now);
    assert.equal(next.choose(),undefined); next.enqueue(); assert.equal(f.jobs.length,2); assert.notEqual(f.jobs[0],f.jobs[1]);
  } finally { await f.close(); }
});

test('a running reservation at the daily limit keeps its owner until both selection and review finish', async () => {
  const f = await fixture();
  const learning = new LearningService(f.store,() => false,f.now);
  try {
    f.memory('tea','一起试过冷泡白茶'); learning.policy = LearningPolicySchema.parse({ daily_calls: 2,idle_seconds: 1 });
    let owner: AbortSignal | undefined, release!: () => void, calls = 0;
    const dialogue = new CompanionDialogue(f.store,f.companion,f.knowledge.relationship,f.projects,{
      enabled: () => learning.policy.enabled,quiet: () => false,
      canReserve: (input_tokens,output_tokens,calls = 1) => learning.repo.canReserve(f.now(),learning.policy,{ calls,input_tokens,output_tokens }),
      enqueue: (kind,id) => learning.enqueue(kind,id),
      analyze: prompt => learning.analyze(prompt,owner!,async () => {
        calls++;
        if (calls === 1) { await new Promise<void>(resolve => { release = resolve; }); return JSON.stringify({ action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '想起冷泡白茶，还挺有意思的。' }); }
        return JSON.stringify({ grounded: true,natural: true,respectful: true });
      }),
    },f.now);
    learning.handlers.set('companion_topic',{ ...INVITATION_BUDGET,run: async (id,signal) => { owner = signal; return dialogue.prepare(id); } });
    f.companion.trigger({ event: 'app_returned' }); dialogue.enqueue(); f.advance(31); learning.tick(); await tick();
    assert.equal(learning.repo.usage(f.now()).calls,2); assert.equal(calls,1); assert.equal(dialogue.waiting(),true);
    assert.equal(f.companion.poll(false,false),null); assert.ok(f.companion.state.pending);
    release(); await tick(); assert.equal(calls,2); assert.ok(f.companion.poll(false,false));
    assert.equal(learning.repo.usage(f.now()).calls,2);
  } finally { await learning.close(); await f.close(); }
});

test('a deferred decision releases its unused review call so the default daily budget can fund one re-evaluation', async () => {
  const f = await fixture(), learning = new LearningService(f.store,() => false,f.now);
  try {
    f.memory('tea','一起试过冷泡白茶'); learning.policy = LearningPolicySchema.parse({ idle_seconds: 1 });
    let owner: AbortSignal | undefined, calls = 0;
    const prompts: string[] = [];
    const dialogue = new CompanionDialogue(f.store,f.companion,f.knowledge.relationship,f.projects,{
      enabled: () => true,quiet: () => false,
      canReserve: (input_tokens,output_tokens,calls = 1) => learning.repo.canReserve(f.now(),learning.policy,{ calls,input_tokens,output_tokens }),
      enqueue: (kind,id) => learning.enqueue(kind,id),
      analyze: prompt => learning.analyze(prompt,owner!,async () => {
        prompts.push(prompt); calls++;
        return JSON.stringify(calls === 1 ? { action: 'defer',reason: 'too_soon' } : calls === 2 ?
          { action: 'speak',source_id: 'tea',quote: '冷泡白茶',text: '想起冷泡白茶，还挺有意思的。' } : { grounded: true,natural: true,respectful: true });
      }),
    },f.now);
    learning.handlers.set('companion_topic',{ ...INVITATION_BUDGET,releaseUnusedCalls: true,
      run: async (id,signal) => { owner = signal; return dialogue.prepare(id); } });
    f.companion.trigger({ event: 'conversation_finished' }); dialogue.enqueue(); f.advance(31); learning.tick(); await tick();
    assert.equal(learning.repo.usage(f.now()).calls,1); assert.equal(learning.repo.usage(f.now()).output_tokens,1024);
    assert.equal(f.companion.poll(false,false),null);
    f.advance(300); dialogue.enqueue(); learning.tick(); await tick();
    assert.equal(calls,3); assert.equal(learning.repo.usage(f.now()).output_tokens,3072); assert.ok(f.companion.poll(false,false));
    const material = JSON.parse(prompts[1]!.slice(prompts[1]!.lastIndexOf('\n') + 1));
    assert.ok(material.elapsed_seconds >= 300);
  } finally { await learning.close(); await f.close(); }
});
