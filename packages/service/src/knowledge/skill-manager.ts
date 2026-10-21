import { randomUUID, createHash } from 'node:crypto';
import { join } from 'node:path';
import { isDeepStrictEqual } from 'node:util';
import { SkillRecordSchema, SkillCandidateSchema, JsonRecordSchema, responseSchemas, localTimestamp, type SkillRecord, type SkillCandidate, type SkillSave } from '@lobuddy/contracts';
import { stableIdentity, validateSkill } from '@lobuddy/domain';
import { SkillKnowledge } from './skills.js';
import { parseStoredJson } from '../storage/json.js';
import type { Handlers } from '../rpc-server.js';
export class SkillManager extends SkillKnowledge {
  list(): SkillRecord[] { return this.store.connection.prepare('SELECT * FROM skill_record ORDER BY updated_at DESC LIMIT 1000').all().map(row => SkillRecordSchema.parse(row)); }
  private path(record: SkillRecord): string {
    const path = `skills/${record.name}/SKILL.md`; this.workspace.path(path);
    if (record.path && record.path !== join(this.workspace.root,path)) throw Error('旧技能路径需要迁移确认'); return path;
  }
  private write(record: SkillRecord,event: string): void {
    const value = SkillRecordSchema.parse(record),path = this.path(value); value.path = join(this.workspace.root,path);
    const keys = Object.keys(value) as (keyof SkillRecord)[];
    this.store.run(`INSERT INTO skill_record(${keys.join(',')}) VALUES(${keys.map(() => '?').join(',')}) ON CONFLICT(id) DO UPDATE SET ${keys.filter(k => !['id','created_at'].includes(k)).map(k => `${k}=excluded.${k}`).join(',')}`,...keys.map(key => value[key]));
    this.store.run('INSERT OR IGNORE INTO skill_version VALUES(?,?,?,?,?,?)',value.id,value.version,value.content,value.description,value.source,value.updated_at);
    this.store.run('INSERT INTO skill_event VALUES(?,?,?,?,?,?)',randomUUID(),value.id,event,`技能版本 ${value.version}`,value.source_session_id,localTimestamp());
    this.store.run('INSERT OR REPLACE INTO knowledge_state VALUES(?,?)','sync-skill:' + value.id,value.id);
  }
  override recover(): void {
    super.recover();
    for (const row of this.store.connection.prepare("SELECT name,value FROM knowledge_state WHERE name LIKE 'sync-skill:%'").all()) {
      const record = this.record(String(row.value)),path = this.path(record);
      if (record.status === 'active') { this.workspace.ensureDirectories(`skills/${record.name}`); this.workspace.atomicWrite(path,record.content); }
      else {
        if (record.status === 'archived') { this.data.ensureDirectories('skills/archive'); this.data.atomicWrite(`skills/archive/${record.name}_v${record.version}.md`,record.content); }
        if (this.workspace.exists(path)) this.workspace.removeFile(path);
      }
      this.store.run('DELETE FROM knowledge_state WHERE name=?',row.name!);
    }
  }
  save(requestId: string,params: SkillSave): SkillRecord {
    validateSkill(params.content);
    const requestKey = 'skill-save:' + requestId,fingerprint = createHash('sha256').update(JSON.stringify(params)).digest('hex');
    const replay = this.store.connection.prepare('SELECT value FROM knowledge_state WHERE name=?').get(requestKey);
    if (replay) {
      const prior = JsonRecordSchema.parse(parseStoredJson(String(replay.value)));
      if (prior.fingerprint !== fingerprint || typeof prior.id !== 'string') throw Error('请求 ID 已用于不同技能修改');
      this.recover(); return this.record(prior.id);
    }
    const previous = params.skill_id ? this.record(params.skill_id) : undefined;
    if (previous && previous.name !== params.name) throw Error('技能名称不能在修订时改变');
    if (previous) this.content(previous);
    const value = SkillRecordSchema.parse({ ...(previous ?? { id: stableIdentity('skill:' + requestId),status: 'active',path: '' }),
      name: params.name,content: params.content,description: params.description,version: previous ? previous.version + 1 : 1,updated_at: localTimestamp() });
    const existing = this.list().find(skill => skill.name === value.name);
    if (!previous && existing) {
      if (existing.id === value.id && this.content(existing) === value.content && existing.description === value.description) return existing;
      throw Error('技能名称已存在');
    }
    this.store.transaction(() => {
      this.write(value,previous ? 'patch' : 'create');
      this.store.run('INSERT INTO knowledge_state VALUES(?,?)',requestKey,JSON.stringify({ fingerprint,id: value.id }));
    }); this.recover(); return this.record(value.id);
  }
  toggle(id: string,status: 'active' | 'disabled' | 'archived'): boolean {
    const value = this.record(id); value.content = this.content(value);
    if (status === 'active') validateSkill(value.content);
    value.status = status; value.updated_at = localTimestamp();
    this.store.transaction(() => this.write(value,status)); this.recover(); return true;
  }
  versions(id: string) {
    this.content(this.record(id)); return responseSchemas['skill.versions'].parse(this.store.connection.prepare('SELECT * FROM skill_version WHERE skill_id=? ORDER BY version DESC').all(id));
  }
  candidates(): SkillCandidate[] {
    return this.store.connection.prepare('SELECT * FROM skill_candidate ORDER BY created_at DESC LIMIT 10000').all().map(row =>
      SkillCandidateSchema.parse({ ...JsonRecordSchema.parse(parseStoredJson(String(row.metadata))),...row }));
  }
  candidate(id: string): SkillCandidate | undefined { return this.candidates().find(item => item.id === id); }
  createCandidate(input: SkillCandidate): SkillCandidate {
    const value = SkillCandidateSchema.parse(input),{ status: _status,updated_at: _updated,created_at: _created,reject_reason: _reason,...body } = value;
    const existing = this.candidate(value.id);
    this.store.transaction(() => {
      const previous = this.store.connection.prepare('SELECT body FROM skill_candidate_revision WHERE candidate_id=? AND revision=?').get(value.id,value.revision);
      if (previous && !isDeepStrictEqual(parseStoredJson(String(previous.body)),body)) throw Error('候选修订不可覆盖');
      if (existing && existing.status !== 'pending') {
        if (previous) return;
        throw Error('已处理候选不能重新修订，请创建新候选');
      }
      this.store.run('INSERT OR IGNORE INTO skill_candidate_revision VALUES(?,?,?)',value.id,value.revision,JSON.stringify(body));
      this.store.run('INSERT OR REPLACE INTO skill_candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',value.id,value.title,value.rationale,value.proposed_name,value.proposed_content,value.source_session_id,value.source_task_id,value.confidence,value.status,value.created_at,value.updated_at,JSON.stringify(value));
    }); return this.candidate(value.id)!;
  }
  resolve(id: string,approved: boolean): boolean {
    const value = this.candidate(id); if (!value || value.status !== 'pending') throw Error('候选已处理');
    if (typeof value.evidence.turn_id === 'string' && this.store.connection.prepare('SELECT 1 FROM relationship_barrier WHERE source_id=?').get(value.evidence.turn_id)) throw Error('候选来源已遗忘');
    if (approved) validateSkill(value.proposed_content);
    this.store.transaction(() => {
      if (approved) this.write(SkillRecordSchema.parse({ id: stableIdentity('candidate-skill:' + id),name: value.proposed_name,path: '',description: value.title,
        content: value.proposed_content,status: 'active',source: 'auto',source_session_id: value.source_session_id }),'approve');
      this.store.run('UPDATE skill_candidate SET status=?,updated_at=? WHERE id=?',approved ? 'approved' : 'rejected',localTimestamp(),id);
    }); this.recover(); return true;
  }
  handlers(): Handlers {
    return { 'skill.list': () => this.list(),'skill.get': p => {
      const record = this.record(p.skill_id); try { return { record,content: this.content(record),content_error: '' }; }
      catch { return { record,content: null,content_error: '技能正文缺失或路径无效，请恢复原文件或编辑补全' }; }
    },'skill.save': (p,c) => this.save(c.requestId,p),'skill.toggle': p => ({ changed: this.toggle(p.skill_id,p.enabled ? 'active' : 'disabled') }),
    'skill.archive': p => ({ changed: this.toggle(p.skill_id,'archived') }),'skill.versions': p => this.versions(p.skill_id),
    'skill.candidates': () => this.candidates().filter(c => c.status === 'pending').slice(0,50),'skill.candidate.resolve': p => ({ changed: this.resolve(p.candidate_id,p.approved) }) };
  }
}
