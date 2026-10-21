import { lstatSync, realpathSync } from 'node:fs';
import { join, dirname, basename } from 'node:path';
import { SkillRecordSchema, SkillCandidateSchema, localTimestamp, type SkillRecord, type TurnState } from '@lobuddy/contracts';
import { casefold, unicodeCompare } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { parseStoredJson } from '../storage/json.js';
import { WorkspaceFiles } from '../tools/files.js';

const NAME = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/u;
const REMOVED = '[用户已遗忘此来源]';
class SkillFiles extends WorkspaceFiles {
  override path(value: string): string {
    if (!/^(?:skills(?:\/[A-Za-z0-9][A-Za-z0-9_-]{0,79}(?:\/SKILL\.md)?)?|skills\/archive(?:\/[A-Za-z0-9][A-Za-z0-9_-]{0,79}_v[0-9]+\.md)?)$/u.test(value)) throw Error('技能投影路径无效');
    return value;
  }
  exists(value: string): boolean {
    this.path(value);
    try {
      const stat = lstatSync(join(this.root,value));
      if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory()) || stat.isFile() && stat.nlink !== 1) throw Error('技能投影不能经过链接或特殊文件');
      return true;
    } catch (error) { if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false; throw error; }
  }
}
/** Read existing skills and erase dependent content through the same canonical SQLite authority. */
export class SkillKnowledge {
  private readonly workspace: SkillFiles;
  private readonly data: SkillFiles;
  constructor(readonly store: Store, workspace: string, data: string) {
    this.workspace = new SkillFiles(workspace,[]); this.data = new SkillFiles(data,[]);
  }
  record(id: string): SkillRecord {
    const row = this.store.connection.prepare('SELECT * FROM skill_record WHERE id=?').get(id);
    if (!row) throw Error('技能不存在'); return SkillRecordSchema.parse(row);
  }
  content(record: SkillRecord): string {
    if (record.content) return record.content;
    if (!NAME.test(record.name)) throw Error('技能名称无效');
    const path = `skills/${record.name}/SKILL.md`;
    if (record.path && join(realpathSync(dirname(record.path)),basename(record.path)) !== join(this.workspace.root,path)) throw Error('旧技能路径需要迁移确认');
    const content = new TextDecoder('utf-8',{ fatal: true }).decode(this.workspace.readBytes(path,256000));
    if (!content.trim() || [...content].length > 64000) throw Error('旧技能内容无效');
    this.store.transaction(() => {
      this.store.run('UPDATE skill_record SET content=? WHERE id=?',content,record.id);
      this.store.run('INSERT OR IGNORE INTO skill_version VALUES(?,?,?,?,?,?)',record.id,record.version,content,record.description,record.source,record.updated_at);
    });
    return content;
  }
  read(id: string, state: TurnState): string {
    const record = this.record(id);
    if (record.status !== 'active' || record.expires_at && new Date(record.expires_at).getTime() <= Date.now()) throw Error('技能未启用或已过期');
    const content = this.content(record);
    this.store.transaction(() => {
      this.store.run('INSERT OR IGNORE INTO skill_use VALUES(?,?)',state.task_id,id);
      this.store.run('UPDATE skill_record SET last_used_at=? WHERE id=?',localTimestamp(),id);
    });
    return content;
  }
  context(state: TurnState): string {
    const terms = (text: string) => {
      const value = casefold(text), result = new Set(value.match(/[a-z0-9_-]+/gu) ?? []);
      for (const segment of value.match(/[\u4e00-\u9fff]+/gu) ?? []) for (let i = 0; i < segment.length - 1; i++) result.add(segment.slice(i,i + 2));
      return result;
    };
    const wanted = terms(state.input_text);
    const ranked = this.store.connection.prepare("SELECT * FROM skill_record WHERE status='active' ORDER BY updated_at DESC LIMIT 1000").all()
      .map(row => SkillRecordSchema.parse(row)).filter(s => !s.expires_at || new Date(s.expires_at).getTime() > Date.now())
      .map(skill => ({ skill, score: [...terms(skill.name + ' ' + skill.description)].filter(t => wanted.has(t)).length }))
      .filter(value => value.score > 0).sort((a,b) => b.score - a.score || unicodeCompare(a.skill.name,b.skill.name));
    let remaining = 12000; const selected = [];
    for (const { skill } of ranked.slice(0,8)) {
      const cost = [...(skill.id + skill.name + skill.description)].length + 100;
      if (cost <= remaining) { remaining -= cost; selected.push({ id: skill.id,name: skill.name,description: skill.description }); }
    }
    return selected.length ? JSON.stringify({ skills: selected }) : '';
  }
  forget(sources: Set<string>): void {
    const candidates = this.store.connection.prepare('SELECT * FROM skill_candidate').all().map(row =>
      SkillCandidateSchema.parse({ ...row,...(parseStoredJson(String(row.metadata)) as Record<string,unknown>) }));
    this.store.transaction(() => {
      for (const candidate of candidates) {
        if (typeof candidate.evidence.turn_id !== 'string' || !sources.has(candidate.evidence.turn_id)) continue;
        const record = this.store.connection.prepare("SELECT id,name FROM skill_record WHERE name=? AND source='auto'").get(candidate.proposed_name);
        if (record) {
          this.store.run("UPDATE skill_record SET status='disabled',content=?,description=?,updated_at=? WHERE id=?",REMOVED,REMOVED,localTimestamp(),record.id!);
          this.store.run('UPDATE skill_version SET content=?,description=? WHERE skill_id=?',REMOVED,REMOVED,record.id!);
          this.store.run('UPDATE skill_event SET detail=? WHERE skill_id=?',REMOVED,record.id!);
          this.store.run('INSERT OR REPLACE INTO knowledge_state VALUES(?,?)',`forget-skill:${record.id}`,record.name!);
        }
        this.store.run('DELETE FROM skill_candidate_revision WHERE candidate_id=?',candidate.id);
        this.store.run("UPDATE skill_candidate SET title=?,proposed_content='',metadata='{}',status='rejected',rationale='来源已遗忘' WHERE id=?",REMOVED,candidate.id);
      }
    });
    this.recover();
  }
  recover(): void {
    for (const row of this.store.connection.prepare("SELECT name,value FROM knowledge_state WHERE name LIKE 'forget-skill:%'").all()) {
      const name = String(row.value); if (!NAME.test(name)) throw Error('待清理的技能名称无效');
      const path = `skills/${name}/SKILL.md`;
      if (this.workspace.exists(path)) this.workspace.atomicWrite(path,REMOVED);
      if (this.data.exists('skills/archive')) for (const leaf of this.data.list('skills/archive',10000)) {
        if (leaf.startsWith(`${name}_v`) && /^.+_v[0-9]+\.md$/u.test(leaf)) {
          const archived = `skills/archive/${leaf}`;
          if (this.data.exists(archived)) this.data.atomicWrite(archived,REMOVED);
        }
      }
      this.store.run('DELETE FROM knowledge_state WHERE name=?',row.name!);
    }
  }
}
