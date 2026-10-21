import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import sharp from 'sharp';
import { MemoryItemSchema, TurnStateSchema, localTimestamp, ChatSessionSchema, ChatMessageSchema, CompanionPreferencesSchema } from '@lobuddy/contracts';
import { contrastRatio, rgb, shiftLightness } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { runtimeSettings } from './config/settings.js';
import { KnowledgeService } from './knowledge/service.js';
import { learnSkill } from './knowledge/skill-learning.js';
import { LearningService } from './knowledge/learning.js';
import { Temporal } from '@js-temporal/polyfill';
import { setImmediate as tick } from 'node:timers/promises';
import { LearningPolicySchema, NotificationViewSchema } from '@lobuddy/contracts';
import { NotificationRepository } from './storage/notifications.js';
import { SkillKnowledge } from './knowledge/skills.js';
import { ProjectService } from './knowledge/projects.js';
import { CompanionDialogue } from './companion/dialogue.js';
import { Companionship } from './companion/policy.js';
import { CompanionAppearance } from './companion/appearance.js';
import { ThemeService } from './companion/themes.js';
import { ImageStore } from './tools/images.js';
import { ChatRepository } from './storage/chat.js';
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-content-ts-')), data = join(root,'data'), workspace = join(root,'workspace');
  await mkdir(workspace); const store = new Store(join(data,'lobuddy.db'),{ create: true });
  const settings = runtimeSettings({ data,workspace,logs: join(root,'logs') });
  const knowledge = new KnowledgeService(store,() => settings);
  const chat = new ChatRepository(store); chat.saveSession(ChatSessionSchema.parse({ id: 's' }));
  const state = TurnStateSchema.parse({ session_id: 's',turn_id: 't',task_id: 'task',engine_id: 'engine',input_text: '整理文件',lane: 'foreground',status: 'running' });
  return { root,data,workspace,store,knowledge,chat,state,settings,close: async () => { store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('desktop color math preserves hex conversion, contrast and lightness boundaries', () => {
  assert.deepEqual(rgb('#FF8A3D'), [255, 138, 61]);
  assert.equal(shiftLightness('#FF8A3D', 0), '#ff8a3d');
  assert.equal(contrastRatio('#FFFFFF', '#000000'), 21);
  assert.equal(contrastRatio('#000000', '#FFFFFF'), 21);
  assert.equal(contrastRatio('#367572', '#367572'), 1);
  assert.ok(rgb(shiftLightness('#000000', 0.2)).every(value => value > 0));
  assert.ok(rgb(shiftLightness('#FFFFFF', -0.2)).every(value => value < 255));
  assert.equal(shiftLightness('#FFFFFF', 1), '#ffffff');
  assert.equal(shiftLightness('#000000', -1), '#000000');
});
test('named themes preserve legacy colors, exclusive activation and saved appearance across restart', async () => {
  const f = await fixture();
  try {
    const appearance = new CompanionAppearance(f.store, f.data), images = new ImageStore(join(f.data, 'images'));
    const themes = new ThemeService(f.store, appearance, images, join(f.data, 'images'));
    const saved = themes.save({ name: 'Test Theme', accent: '#FF8A3D', side: '#FFF8EF' });
    assert.deepEqual(themes.list(), [saved]);
    const row = f.store.connection.prepare('SELECT colors_json FROM user_themes WHERE id=?').get(saved.theme_id)!;
    assert.deepEqual(JSON.parse(String(row.colors_json)), { primary: '#FF8A3D', side: '#FFF8EF' });
    f.store.run('INSERT INTO user_themes VALUES(?,?,?,?,NULL,0,?,?)', 'legacy', '旧主题', 'manual', JSON.stringify({ primary: '#123456', primary_soft: '#abcdef' }), localTimestamp(), localTimestamp());
    assert.deepEqual(themes.list().find(item => item.theme_id === 'legacy'), { theme_id: 'legacy', name: '旧主题', accent: '#123456', side: '#abcdef' });
    await themes.apply(saved.theme_id); await themes.apply('legacy');
    assert.deepEqual(f.store.connection.prepare('SELECT id FROM user_themes WHERE is_active=1').all().map(row => row.id), ['legacy']);
    const restored = new CompanionAppearance(f.store, f.data);
    assert.equal(restored.value.accent, '#123456'); assert.equal(restored.value.side, '#abcdef');
    assert.equal(themes.remove(saved.theme_id), true); assert.equal(themes.remove(saved.theme_id), false);
    await assert.rejects(themes.apply(saved.theme_id), /不存在/);
    assert.equal(appearance.value.accent, '#123456');
  } finally { await f.close(); }
});
test('prepared invitation uses an exact source quote, rejects invented text and expires on source changes or quiet boundaries', async () => {
  const f = await fixture();
  try {
    let now = 1800000000; const companion = new Companionship(f.store,() => now);
    const projects = new ProjectService(f.store,f.knowledge.relationship,new AbortController().signal,() => now);
    const jobs: string[] = []; let reply = '', finish: (() => void) | undefined;
    const dialogue = new CompanionDialogue(f.store,companion,f.knowledge.relationship,projects,{
      enabled: () => true, quiet: () => false, canReserve: () => true, enqueue: (_kind,source) => { jobs.push(source); },
      analyze: async () => { if (finish) await new Promise<void>(resolve => { finish = resolve; }); return reply; },
    },() => now);
    const memory = f.knowledge.gateway.saveManual(MemoryItemSchema.parse({ id: 'experience',memory_type: 'episodic_memory',title: '共同经历',content: '我们一起整理了相册。' }));
    const draft = (quote: string) => JSON.stringify({ source_id: memory.id,quote,opening: '我还记得你说',closing: '我们可以慢慢来。' });
    companion.trigger({ event: 'conversation_finished' }); dialogue.enqueue(); assert.equal(jobs.length,1);
    reply = draft('我们去过台湾'); assert.equal((await dialogue.prepare(jobs[0]!)).skipped,'invalid_source_or_quote');
    assert.equal(dialogue.choose(),undefined);
    reply = JSON.stringify({ ...JSON.parse(draft('一起整理了相册')),source_id: 'invented' });
    assert.equal((await dialogue.prepare(jobs[0]!)).skipped,'invalid_source_or_quote');
    reply = draft('一起整理了相册'); assert.equal((await dialogue.prepare(jobs[0]!)).prepared,true);
    assert.match(dialogue.choose()!.text,/一起整理了相册/);
    dialogue.respond({ ...f.state,input_text: '今天不聊相册' }); assert.equal(dialogue.choose(),undefined); assert.equal(dialogue.blocked(memory.content),true);
    now += 86400; assert.equal(dialogue.blocked(memory.content),false);
    dialogue.respond({ ...f.state,input_text: '以后别提相册' }); now += 86400 * 7; assert.equal(dialogue.blocked(memory.content),true);
    dialogue.release(dialogue.boundaries()[0]!.id);
    companion.state.pending = ''; companion.trigger({ event: 'conversation_finished' }); dialogue.enqueue();
    finish = () => {}; const pending = dialogue.prepare(jobs.at(-1)!); await Promise.resolve();
    f.knowledge.gateway.delete(memory.id); f.knowledge.relationship.invalidate(); finish!(); assert.equal((await pending).skipped,'invalid_source_or_quote');
    f.knowledge.gateway.delete(memory.id); assert.equal(dialogue.source(memory.id),undefined);
  } finally { await f.close(); }
});
test('appearance validates full animations, preserves bytes and restores custom identity; image themes retain readable contrast', async () => {
  const f = await fixture();
  try {
    const appearance = new CompanionAppearance(f.store,f.data); await appearance.initialize();
    const imagePath = join(f.root,'pet.gif');
    const bytes = await sharp({ create: { width: 8,height: 16,channels: 3,background: '#73cfbd',pageHeight: 8 } }).gif({ loop: 0,delay: [100,100] }).toBuffer();
    await writeFile(imagePath,bytes); const value = await appearance.importImage(imagePath);
    assert.equal(value.sprite,'custom'); assert.ok(value.image_id);
    assert.deepEqual(await readFile(join(f.data,'pet-images',value.image_id!)),bytes);
    const restarted = new CompanionAppearance(f.store,f.data); assert.deepEqual(restarted.value,value);
    const bad = join(f.root,'broken.gif'); await writeFile(bad,bytes.subarray(0,bytes.length / 2));
    await assert.rejects(appearance.importImage(bad)); assert.equal(appearance.value.image_id,value.image_id);
    const images = new ImageStore(join(f.data,'images')), image = await images.importFile(imagePath);
    const themes = new ThemeService(f.store,appearance,images,join(f.data,'images'));
    const generated = await themes.fromImage(image.image_id); assert.ok(contrastRatio(generated.accent,'#ffffff') >= 4.5);
    const saved = themes.save(generated); await themes.apply(saved.theme_id); assert.equal(appearance.value.accent,saved.accent);
    assert.equal(themes.remove(saved.theme_id),true); await assert.rejects(themes.apply(saved.theme_id),/不存在/);
  } finally { await f.close(); }
});
test('appearance imports legacy display preferences without geometry and rejects invalid replacement settings', async () => {
  const f = await fixture();
  try {
    await writeFile(join(f.data, 'pet_appearance.json'), JSON.stringify({ scale: 1.5, opacity: 0.5, always_on_top: false, position_x: -9999 }));
    const appearance = new CompanionAppearance(f.store, f.data); await appearance.initialize();
    assert.equal(appearance.value.scale, 1.5); assert.equal(appearance.value.opacity, 0.5); assert.equal(appearance.value.always_on_top, false);
    assert.equal(Object.hasOwn(appearance.value, 'position_x'), false);
    await appearance.save(CompanionPreferencesSchema.parse({ sprite: 'skadi', scale: 1.5, accent: '#223344' }));
    const restored = new CompanionAppearance(f.store, f.data);
    assert.equal(restored.value.sprite, 'skadi'); assert.equal(restored.value.scale, 1.5);
    assert.throws(() => CompanionPreferencesSchema.parse({ accent: 'url(https://example.com)' }));
    assert.throws(() => CompanionPreferencesSchema.parse({ scale: 5 }));
    await assert.rejects(appearance.save(CompanionPreferencesSchema.parse({ sprite: 'custom' })), /先选择/);
    assert.deepEqual(appearance.value, restored.value);
  } finally { await f.close(); }
});
test('skill reading imports the original body, excludes irrelevant or disabled skills and never counts a read as success', async () => {
  const f = await fixture();
  try {
    assert.equal(f.knowledge.skills.context(f.state), ''); assert.deepEqual(f.knowledge.activeSkills(), []);
    const path = join(f.workspace,'skills/organize/SKILL.md'); await mkdir(join(f.workspace,'skills/organize'),{ recursive: true });
    await writeFile(path,'# 整理文件\n先预览，再审批。');
    f.store.run('INSERT INTO skill_record(id,name,path,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)','skill','organize',path,'整理文件','active',localTimestamp(),localTimestamp());
    const skills = new SkillKnowledge(f.store,f.workspace,f.data);
    assert.match(skills.context(f.state),/organize/); assert.match(skills.context(f.state),/整理文件/);
    assert.equal(f.knowledge.activeSkills().length, 1); assert.equal(skills.context({ ...f.state,input_text: '晚安' }),'');
    assert.match(skills.read('skill',f.state),/先预览，再审批/);
    assert.equal(skills.record('skill').success_count,0); assert.equal(f.store.connection.prepare('SELECT count(*) n FROM skill_version').get()!.n,1);
    f.store.run("UPDATE skill_record SET status='disabled' WHERE id='skill'");
    assert.equal(skills.context(f.state),''); assert.throws(() => skills.read('skill',f.state),/未启用/);
  } finally { await f.close(); }
});
test('forgetting removes dependent skill bodies and archives; interrupted activation cannot restore a blocked fact', async () => {
  const f = await fixture();
  try {
    f.chat.saveMessage(ChatMessageSchema.parse({ id: 'source',session_id: 's',role: 'user',content: '我喜欢红茶' }));
    const relation = f.knowledge.relationship.admit({ kind: 'preference',key: 'drink',content: '我喜欢红茶',quote: '我喜欢红茶',source_ids: ['source'] },'s')!;
    const path = join(f.workspace,'skills/tea/SKILL.md'), archive = join(f.data,'skills/archive/tea_v1.md');
    await mkdir(join(f.workspace,'skills/tea'),{ recursive: true }); await mkdir(join(f.data,'skills/archive'),{ recursive: true });
    await writeFile(path,'我喜欢红茶'); await writeFile(archive,'我喜欢红茶');
    f.store.run('INSERT INTO skill_record(id,name,path,description,content,status,source,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)','skill','tea',path,'红茶','我喜欢红茶','active','auto',localTimestamp(),localTimestamp());
    f.store.run('INSERT INTO skill_version VALUES(?,?,?,?,?,?)','skill',1,'我喜欢红茶','红茶','auto',localTimestamp());
    f.store.run('INSERT INTO skill_candidate(id,title,rationale,proposed_name,proposed_content,created_at,updated_at,metadata) VALUES(?,?,?,?,?,?,?,?)','candidate','茶','用户纠正','tea','我喜欢红茶',localTimestamp(),localTimestamp(),JSON.stringify({ evidence: { turn_id: 'source' } }));
    f.store.run('INSERT INTO learning_job(id,kind,source_id,updated_at) VALUES(?,?,?,?)', 'job-source', 'skill_learning', 'source', 1);
    f.knowledge.relationship.forget(relation.id,true);
    assert.equal(f.store.connection.prepare("SELECT status FROM skill_record WHERE id='skill'").get()!.status,'disabled');
    const job = f.store.connection.prepare('SELECT status,attempts FROM learning_job WHERE id=?').get('job-source')!;
    assert.equal(job.status, 'interrupted'); assert.equal(job.attempts, 3);
    for (const file of [path,archive]) assert.doesNotMatch(await readFile(file,'utf8'),/红茶/);
    assert.doesNotMatch(String(f.store.connection.prepare("SELECT content FROM skill_version WHERE skill_id='skill'").get()!.content),/红茶/);
    // Simulate a crash after the source barrier, before the applying row was cleared.
    f.store.run("UPDATE relationship SET status='applying',content='我喜欢红茶' WHERE id=?",relation.id);
    f.knowledge.relationship.recover(); assert.equal(f.knowledge.relationship.get(relation.id).status,'forgotten');
    assert.equal(f.knowledge.relationship.context('s'),''); assert.equal(f.knowledge.repo.get(relation.id),undefined);
    const state = TurnStateSchema.parse({ turn_id: 'source',task_id: 'task',session_id: 's',engine_id: 'e',lane: 'foreground',status: 'completed',input_text: '以后整理文件时先给我按类型的数量。' });
    assert.deepEqual(learnSkill(f.knowledge.skills,state),{ skipped: 'forgotten_source' });
    const restarted = new KnowledgeService(f.store,() => f.settings);
    assert.deepEqual(learnSkill(restarted.skills,state),{ skipped: 'forgotten_source' });
  } finally { await f.close(); }
});

test('appearance defaults, malformed legacy data and invalid imports preserve the last usable state', async () => {
  const f = await fixture();
  try {
    const appearance = new CompanionAppearance(f.store, f.data); await appearance.initialize();
    assert.equal(appearance.value.scale, 1); assert.equal(appearance.value.opacity, 1); assert.equal(appearance.value.always_on_top, true);
    for (const input of [{ scale: 0.1 }, { scale: 3 }, { opacity: 0.1 }, { opacity: 1.5 }]) assert.throws(() => CompanionPreferencesSchema.parse(input));
    const malformed = '{not JSON'; await writeFile(join(f.data, 'pet_appearance.json'), malformed);
    await appearance.initialize();
    assert.equal(await readFile(join(f.data, 'pet_appearance.json'), 'utf8'), malformed);
    const initial = { ...appearance.value };
    await assert.rejects(appearance.importImage(join(f.root, 'missing.png')));
    for (const [name, bytes] of [['plain.txt', Buffer.from('hello')], ['fake.png', Buffer.alloc(100, 'x')], ['huge.png', Buffer.alloc(21 * 1024 * 1024)]] as const) {
      const path = join(f.root, name); await writeFile(path, bytes); await assert.rejects(appearance.importImage(path));
      assert.deepEqual(appearance.value, initial);
    }
  } finally { await f.close(); }
});

test('listening is temporary and session scoped; quoted boundaries are ignored and today ends at local midnight', async () => {
  const f = await fixture();
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    let now = Temporal.ZonedDateTime.from({ timeZone: zone,year: 2026,month: 10,day: 21,hour: 23,minute: 59 }).epochMilliseconds / 1000;
    const companion = new Companionship(f.store,() => now);
    const projects = new ProjectService(f.store,f.knowledge.relationship,new AbortController().signal,() => now);
    const dialogue = new CompanionDialogue(f.store,companion,f.knowledge.relationship,projects,{
      enabled: () => false,quiet: () => false,canReserve: () => false,enqueue: () => assert.fail(),analyze: async () => { throw Error('unexpected model'); },
    },() => now);
    for (const input_text of ['他说“先听我讲”','如果今天不聊工作','今天不聊工作？','角色扮演：今天不聊工作']) {
      dialogue.respond({ ...f.state,input_text }); assert.equal(dialogue.state('s'),undefined); assert.deepEqual(dialogue.boundaries(),[]);
    }
    dialogue.respond({ ...f.state,input_text: '先听我讲' }); assert.equal(dialogue.state('s')!.mode,'listening');
    assert.equal(dialogue.state('other'),undefined); assert.match(dialogue.context(f.state),/不连续追问/);
    now += 3601; assert.equal(dialogue.state('s'),undefined);
    dialogue.respond({ ...f.state,input_text: '我好累' }); assert.equal(dialogue.state('s')!.mode,'listening');
    dialogue.respond({ ...f.state,input_text: '帮我分析一下' }); assert.equal(dialogue.state('s')!.mode,'discussing');
    now -= 3601;
    dialogue.respond({ ...f.state,input_text: '今天不聊工作' }); assert.equal(dialogue.boundaries()[0]!.expires_at,now + 60);
    assert.equal(dialogue.blocked('工作项目'),true); assert.equal(dialogue.blocked('喝水提醒'),false);
    const notifications = new NotificationRepository(f.store,() => now);
    notifications.eligible = value => !dialogue.blocked(value.text);
    notifications.put(NotificationViewSchema.parse({ id: 'work-notice',reason: 'task_result',source_id: 'task',text: '工作结果完成',planned_at: now,created_at: now }));
    assert.equal(notifications.next(false),null); assert.equal(notifications.list()[0]!.status,'pending');
    now += 61; assert.equal(dialogue.blocked('工作项目'),false); assert.ok(notifications.next(false));
    dialogue.respond({ ...f.state,input_text: '以后别提工作' }); assert.equal(dialogue.boundaries()[0]!.expires_at,null);
    dialogue.release(dialogue.boundaries()[0]!.id); assert.equal(dialogue.blocked('工作项目'),false);
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM delegation').get()!.n,0);
  } finally { await f.close(); }
});

test('grounded invitations use the durable shared budget, stop waiting when disabled, and respect typing, deduplication and ignore feedback', async () => {
  const f = await fixture(); let now = 1800000000, calls = 0;
  const learning = new LearningService(f.store,() => false,() => now);
  try {
    const companion = new Companionship(f.store,() => now);
    const projects = new ProjectService(f.store,f.knowledge.relationship,new AbortController().signal,() => now);
    const memory = f.knowledge.gateway.saveManual(MemoryItemSchema.parse({ id: 'experience-budget',memory_type: 'episodic_memory',title: '共同经历',content: '我们一起完成了提醒功能的测试。' }));
    let signal: AbortSignal | undefined;
    const dialogue = new CompanionDialogue(f.store,companion,f.knowledge.relationship,projects,{
      enabled: () => learning.policy.enabled,quiet: () => false,
      canReserve: (input_tokens,output_tokens) => learning.repo.canReserve(now,learning.policy,{ calls: 1,input_tokens,output_tokens }),
      enqueue: (kind,source) => learning.enqueue(kind,source),
      analyze: async prompt => {
        assert.ok(signal); return learning.analyze(prompt,signal,async text => {
          calls++; assert.match(text,/我们一起完成了提醒功能的测试/);
          return JSON.stringify({ source_id: memory.id,quote: '一起完成了提醒功能的测试',opening: '我还记得你说',closing: '想接着聊时，我在。' });
        });
      },
    },() => now);
    learning.handlers.set('companion_topic',{ calls: 1,input_tokens: 8192,output_tokens: 1024,
      run: async (source,owner) => { signal = owner; try { return await dialogue.prepare(source); } finally { signal = undefined; } } });
    learning.policy = LearningPolicySchema.parse({ enabled: false }); companion.trigger({ event: 'app_returned' });
    dialogue.enqueue(); assert.equal(dialogue.waiting(),false); assert.equal(learning.repo.jobs().length,0);
    learning.policy = LearningPolicySchema.parse({ daily_calls: 0 }); dialogue.enqueue(); now += 61; learning.tick(); await tick();
    assert.equal(calls,0); assert.equal(dialogue.waiting(),false);
    learning.policy = LearningPolicySchema.parse({ daily_calls: 1 }); learning.tick(); await tick();
    assert.equal(calls,1); assert.equal(learning.repo.usage(now).calls,1); learning.tick(); await tick(); assert.equal(calls,1);
    companion.engage({ client: 'quick',typing: true,conversation: true });
    assert.equal(companion.poll(false,false),null); assert.equal(companion.state.used,0);
    now += 11; const notice = companion.poll(false,false)!; assert.ok(notice);
    assert.match(notice.text,/一起完成了提醒功能的测试/); assert.doesNotMatch(notice.text,/？/);
    assert.equal(notice.memory_id,memory.id); assert.equal(dialogue.choose(),undefined); assert.equal(dialogue.valid(memory.id),true);
    companion.feedback({ notice_id: notice.notice_id,action: 'ignored' });
    assert.equal(companion.state.cooldown_until,now + 7200); assert.equal(companion.poll(false,false),null);
    companion.topics.feedback(notice.topic_id,'never'); assert.equal(dialogue.valid(memory.id),false);
  } finally { await learning.close(); await f.close(); }
});
