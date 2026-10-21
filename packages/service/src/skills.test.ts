import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, readFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SkillSaveSchema, SkillCandidateSchema, TurnStateSchema, OutcomeSchema } from '@lobuddy/contracts';
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
