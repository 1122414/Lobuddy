import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, readFile, symlink, writeFile, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SkillSaveSchema, SkillCandidateSchema, SkillRecordSchema, TurnStateSchema, OutcomeSchema } from '@lobuddy/contracts';
import { validateSkill } from '@lobuddy/domain';
import { Store } from './storage/database.js';
import { SkillManager } from './knowledge/skill-manager.js';
import { learnSkill } from './knowledge/skill-learning.js';
import { OutcomeRepository } from './storage/outcomes.js';
const body = (name: string,version = 'one') => `---\nname: ${name}\ndescription: 核对来源\n---\n## When to use\nUse this skill when the user requests a source summary.\n核对来源和结果，不绕过审批。${version}`;
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-skills-ts-')),workspace = join(root,'workspace'),data = join(root,'data');
  await mkdir(workspace); const store = new Store(join(data,'lobuddy.db'),{ create: true }),skills = new SkillManager(store,workspace,data);
  return { root,workspace,data,store,skills,close: async () => { store.close(); await rm(root,{ recursive: true,force: true }); } };
}
test('disabling skills removes only empty managed directories and enabling recreates the projection', async () => {
  const f = await fixture();
  try {
    const record = f.skills.save('cleanup', SkillSaveSchema.parse({ name: 'cleanup', description: 'cleanup', content: body('cleanup') }));
    const directory = join(f.workspace, 'skills/cleanup');
    f.skills.toggle(record.id, 'disabled');
    await assert.rejects(stat(directory), { code: 'ENOENT' });
    f.skills.toggle(record.id, 'active');
    assert.equal(await readFile(join(directory, 'SKILL.md'), 'utf8'), body('cleanup'));
    await writeFile(join(directory, 'user-notes.txt'), 'preserve user file');
    f.skills.toggle(record.id, 'disabled');
    assert.equal(await readFile(join(directory, 'user-notes.txt'), 'utf8'), 'preserve user file');
    await assert.rejects(stat(join(directory, 'SKILL.md')), { code: 'ENOENT' });
    f.skills.recover();
    f.skills.toggle(record.id, 'active');
    f.skills.toggle(record.id, 'archived');
    assert.equal(await readFile(join(directory, 'user-notes.txt'), 'utf8'), 'preserve user file');
    assert.equal(await readFile(join(f.data, 'skills/archive/cleanup_v1.md'), 'utf8'), body('cleanup'));
  } finally { await f.close(); }
});
test('skill edits retain immutable body versions, disabled skills stop reads and projection, and enable restores SQLite content',async () => {
  const f = await fixture();
  try {
    const params = SkillSaveSchema.parse({ name: 'review-source',description: '来源资料检查',content: body('review-source') });
    const record = f.skills.save('one',params); assert.equal(f.skills.save('one',params).id,record.id);
    f.skills.toggle(record.id,'disabled'); await assert.rejects(readFile(join(f.workspace,'skills/review-source/SKILL.md')));
    const state = TurnStateSchema.parse({ turn_id: 'turn',task_id: 'task',session_id: 's',engine_id: 'e',lane: 'foreground',status: 'running',input_text: '资料来源检查' });
    assert.throws(() => f.skills.read(record.id,state),/未启用/); assert.equal(f.skills.context(state),'');
    f.skills.save('patch',{ ...params,skill_id: record.id,content: body('review-source','two') });
    f.skills.save('patch',{ ...params,skill_id: record.id,content: body('review-source','two') });
    assert.equal(f.skills.record(record.id).version,2); assert.equal(f.skills.versions(record.id).length,2);
    assert.equal(f.skills.versions(record.id)[1]!.content,params.content);
    f.skills.toggle(record.id,'active'); assert.equal(await readFile(join(f.workspace,'skills/review-source/SKILL.md'),'utf8'),body('review-source','two'));
    f.skills.read(record.id,state); f.skills.read(record.id,state);
    assert.equal(f.skills.record(record.id).success_count,0); assert.equal(f.store.connection.prepare('SELECT count(*) n FROM skill_use').get()!.n,1);
    f.skills.toggle(record.id,'archived'); assert.equal(await readFile(join(f.data,'skills/archive/review-source_v2.md'),'utf8'),body('review-source','two'));
    await assert.rejects(readFile(join(f.workspace,'skills/review-source/SKILL.md')));
  } finally { await f.close(); }
});
test('skill validation and projection reject invalid triggers, secrets, commands and symlink escapes; pending projection recovers',async () => {
  const f = await fixture();
  try {
    for (const invalid of ['short',body('safe').replace('## When to use','## Intro').replace('Use this skill when the user','Applies to'),body('safe') + '\nrm -rf /',body('safe') + '\nBearer synthetic-secret',body('safe') + '\n' + 'x\n'.repeat(501)]) assert.throws(() => validateSkill(invalid));
    await mkdir(join(f.workspace,'skills')); await symlink(f.root,join(f.workspace,'skills/escape'));
    assert.throws(() => f.skills.save('escape',SkillSaveSchema.parse({ name: 'escape',description: 'safe',content: body('escape') })),/符号链接/);
    await assert.rejects(readFile(join(f.root,'SKILL.md')));
    // The DB remains authoritative and records an unfinished projection instead of losing the skill.
    assert.equal(f.skills.list().length,1); assert.ok(f.store.connection.prepare("SELECT 1 FROM knowledge_state WHERE name LIKE 'sync-skill:%'").get());
    await rm(join(f.workspace,'skills/escape')); f.skills.recover();
    assert.equal(await readFile(join(f.workspace,'skills/escape/SKILL.md'),'utf8'),body('escape'));
  } finally { await f.close(); }
});
test('verified results and diagnosed failures produce source-backed candidates; chat, cancellation and forgotten evidence do not',async () => {
  const f = await fixture();
  try {
    const outcomes = new OutcomeRepository(f.store);
    for (const [index,[status,verdict,scenario]] of ( [['completed','verified','digest'],['failed','failed','organize'],['completed','unknown','chat'],['cancelled','verified','digest']] as const).entries()) {
      const state = TurnStateSchema.parse({ turn_id: 'turn-' + index,task_id: 'task-' + index,session_id: 's',engine_id: 'e',lane: 'background',status,input_text: '归纳资料' });
      outcomes.save(OutcomeSchema.parse({ turn_id: state.turn_id,verdict,scenario,criteria: ['产物来源校验'],evidence: [{ checked: true }] }));
      const result = learnSkill(f.skills,state);
      if (index < 2) {
        assert.ok(result.candidate_id); assert.deepEqual(learnSkill(f.skills,state),result);
        const candidate = f.skills.candidate(result.candidate_id)!; validateSkill(candidate.proposed_content);
        assert.match(candidate.proposed_content,/# 失败反例/); assert.equal(candidate.evidence.turn_id,state.turn_id);
        if (index === 0) { f.skills.resolve(candidate.id,true); assert.equal(f.skills.candidate(candidate.id)!.status,'approved'); }
        else f.skills.resolve(candidate.id,false);
      } else assert.ok(result.skipped);
    }
    const approved = f.skills.candidates().find(c => c.status === 'approved')!,record = f.skills.list()[0]!;
    f.skills.forget(new Set([String(approved.evidence.turn_id)])); assert.equal(f.skills.record(record.id).status,'disabled');
    assert.equal(f.skills.candidate(approved.id)!.status,'rejected'); assert.equal(f.skills.versions(record.id)[0]!.content,'[用户已遗忘此来源]');
    assert.throws(() => f.skills.resolve(approved.id,true),/已处理/);
  } finally { await f.close(); }
});
test('candidate revision bodies cannot be overwritten and approved status overrides stale metadata',async () => {
  const f = await fixture();
  try {
    const candidate = SkillCandidateSchema.parse({ id: 'candidate',title: '资料检查',rationale: '有待审证据',proposed_name: 'candidate-source',proposed_content: body('candidate-source') });
    f.skills.createCandidate(candidate); assert.throws(() => f.skills.createCandidate({ ...candidate,rationale: 'overwrite' }),/不可覆盖/);
    f.skills.resolve(candidate.id,true); assert.equal(f.skills.candidates()[0]!.status,'approved');
    f.skills.createCandidate(candidate); assert.equal(f.skills.candidates()[0]!.status,'approved');
    assert.equal(f.store.connection.prepare('SELECT count(*) n FROM skill_candidate_revision').get()!.n,1);
  } finally { await f.close(); }
});

test('legacy skill path aliases preserve identity through disable and enable without following external projections', async () => {
  const f = await fixture();
  try {
    const record = f.skills.save('aliased', SkillSaveSchema.parse({ name: 'aliased', description: 'same directory', content: body('aliased') }));
    const alias = join(f.root, 'workspace-alias'); await symlink(f.workspace, alias);
    f.store.run('UPDATE skill_record SET path=? WHERE id=?', join(alias, 'skills/aliased/SKILL.md'), record.id);
    assert.equal(f.skills.toggle(record.id, 'disabled'), true);
    await assert.rejects(readFile(record.path));
    assert.equal(f.skills.toggle(record.id, 'active'), true);
    assert.equal(await readFile(record.path, 'utf8'), body('aliased'));
    assert.equal(f.skills.record(record.id).id, record.id);
    assert.equal(f.skills.record(record.id).version, 1);
    const outside = join(f.root, 'outside'); await mkdir(outside); await writeFile(join(outside, 'SKILL.md'), 'preserve');
    f.store.run('UPDATE skill_record SET path=? WHERE id=?', join(outside, 'SKILL.md'), record.id);
    assert.throws(() => f.skills.toggle(record.id, 'disabled'), /迁移确认/);
    assert.equal(await readFile(join(outside, 'SKILL.md'), 'utf8'), 'preserve');
    assert.equal(f.skills.record(record.id).status, 'active');
  } finally { await f.close(); }
});

test('legacy skill backfill preserves actual version numbers and missing bodies cannot be silently enabled', async () => {
  const f = await fixture();
  try {
    const path = join(f.workspace, 'skills/legacy/SKILL.md'); await mkdir(join(f.workspace, 'skills/legacy'), { recursive: true });
    await writeFile(path, body('legacy', 'old'));
    const record = SkillRecordSchema.parse({ id: 'legacy-id', name: 'legacy', description: 'legacy source', path, version: 5, status: 'active' });
    const keys = Object.keys(record) as (keyof typeof record)[];
    f.store.run(`INSERT INTO skill_record(${keys.join(',')}) VALUES(${keys.map(() => '?').join(',')})`, ...keys.map(key => record[key]));
    assert.equal(f.skills.content(record), body('legacy', 'old'));
    assert.deepEqual(f.skills.versions(record.id).map(v => v.version), [5]);
    f.skills.toggle(record.id, 'disabled');
    f.skills.save('revision', SkillSaveSchema.parse({ skill_id: record.id, name: record.name, description: record.description, content: body('legacy', 'new') }));
    assert.deepEqual(f.skills.versions(record.id).map(v => v.version), [6, 5]);
    assert.equal(f.skills.versions(record.id)[1]!.content, body('legacy', 'old')); await assert.rejects(readFile(path));
    f.store.run("UPDATE skill_record SET content='' WHERE id=?", record.id);
    assert.throws(() => f.skills.toggle(record.id, 'active'));
    assert.equal(f.skills.record(record.id).status, 'disabled'); await assert.rejects(readFile(path));
    assert.throws(() => f.skills.save('duplicate', SkillSaveSchema.parse({ name: 'legacy', description: 'another', content: body('legacy') })), /已存在/);
  } finally { await f.close(); }
});
test('explicit method corrections preserve provenance without success claims, and secrets or cancelled turns cannot form candidates', async () => {
  const f = await fixture();
  try {
    const state = TurnStateSchema.parse({ turn_id: 'correction', task_id: 'task', session_id: 'session', engine_id: 'engine',
      lane: 'foreground', status: 'completed', input_text: '下次整理文件时先给我按类型的数量，再让我确认。' });
    const result = learnSkill(f.skills, state), candidate = f.skills.candidate(result.candidate_id!)!;
    assert.equal(candidate.source_kind, 'correction'); assert.equal(candidate.source_session_id, state.session_id);
    assert.equal(candidate.source_task_id, state.task_id); assert.equal(candidate.evidence.verdict, 'unknown');
    assert.equal(candidate.evidence.turn_id, state.turn_id); assert.ok(candidate.proposed_content.includes(state.input_text));
    validateSkill(candidate.proposed_content);
    assert.throws(() => f.skills.createCandidate({ ...candidate, proposed_content: candidate.proposed_content + ' changed' }), /不可覆盖/);
    assert.ok(learnSkill(f.skills, { ...state, turn_id: 'cancelled', status: 'cancelled' }).skipped);
    assert.ok(learnSkill(f.skills, { ...state, turn_id: 'secret', input_text: '下次整理 password=hunter22 Bearer abc123 sk-12345678901234567890 user@example.com' }).skipped);
    const noEvidence = { ...state, turn_id: 'claim', input_text: '模型说全部完成了', output_text: '完成' };
    assert.deepEqual(learnSkill(f.skills, noEvidence), { skipped: 'no_result_evidence' });
    assert.equal(new OutcomeRepository(f.store).finishTurn('claim', 'completed').verdict, 'unknown');
    assert.equal(f.skills.candidates().length, 1);
    assert.doesNotMatch(JSON.stringify(f.skills.candidates()), /hunter22|abc123|user@example.com|sk-12345678901234567890/);
  } finally { await f.close(); }
});
