import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import sharp from 'sharp';
import { MemoryItemSchema, TurnStateSchema, localTimestamp, ChatSessionSchema, ChatMessageSchema } from '@lobuddy/contracts';
import { contrastRatio } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { runtimeSettings } from './config/settings.js';
import { KnowledgeService } from './knowledge/service.js';
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
  return { root,data,workspace,store,knowledge,chat,state,close: async () => { store.close(); await rm(root,{ recursive: true,force: true }); } };
}
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
    reply = draft('一起整理了相册'); assert.equal((await dialogue.prepare(jobs[0]!)).prepared,true);
    assert.match(dialogue.choose()!.text,/一起整理了相册/);
    dialogue.respond({ ...f.state,input_text: '今天不聊相册' }); assert.equal(dialogue.choose(),undefined); assert.equal(dialogue.blocked(memory.content),true);
    now += 86400; assert.equal(dialogue.blocked(memory.content),false);
    dialogue.respond({ ...f.state,input_text: '以后别提相册' }); now += 86400 * 7; assert.equal(dialogue.blocked(memory.content),true);
    dialogue.release(dialogue.boundaries()[0]!.id);
    companion.state.pending = ''; companion.trigger({ event: 'conversation_finished' }); dialogue.enqueue();
    finish = () => {}; const pending = dialogue.prepare(jobs.at(-1)!); await Promise.resolve();
    f.knowledge.relationship.invalidate(); finish!(); assert.equal((await pending).skipped,'invalid_source_or_quote');
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
test('skill reading imports the original body, excludes irrelevant or disabled skills and never counts a read as success', async () => {
  const f = await fixture();
  try {
    const path = join(f.workspace,'skills/organize/SKILL.md'); await mkdir(join(f.workspace,'skills/organize'),{ recursive: true });
    await writeFile(path,'# 整理文件\n先预览，再审批。');
    f.store.run('INSERT INTO skill_record(id,name,path,description,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)','skill','organize',path,'整理文件','active',localTimestamp(),localTimestamp());
    const skills = new SkillKnowledge(f.store,f.workspace,f.data);
    assert.match(skills.context(f.state),/organize/); assert.equal(skills.context({ ...f.state,input_text: '晚安' }),'');
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
    f.knowledge.relationship.forget(relation.id,true);
    assert.equal(f.store.connection.prepare("SELECT status FROM skill_record WHERE id='skill'").get()!.status,'disabled');
    for (const file of [path,archive]) assert.doesNotMatch(await readFile(file,'utf8'),/红茶/);
    assert.doesNotMatch(String(f.store.connection.prepare("SELECT content FROM skill_version WHERE skill_id='skill'").get()!.content),/红茶/);
    // Simulate a crash after the source barrier, before the applying row was cleared.
    f.store.run("UPDATE relationship SET status='applying',content='我喜欢红茶' WHERE id=?",relation.id);
    f.knowledge.relationship.recover(); assert.equal(f.knowledge.relationship.get(relation.id).status,'forgotten');
    assert.equal(f.knowledge.relationship.context('s'),''); assert.equal(f.knowledge.repo.get(relation.id),undefined);
  } finally { await f.close(); }
});
