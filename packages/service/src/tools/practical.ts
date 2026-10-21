import { createHash, randomUUID } from 'node:crypto';
import { dirname, extname } from 'node:path';
import { OutcomeSchema, type OrganizeArguments, type DigestArguments, type Outcome } from '@lobuddy/contracts';
import { WorkspaceFiles } from './files.js';
import { OutcomeRepository } from '../storage/outcomes.js';
import { fetchPage } from './web.js';
type Entry = { source: string; target: string; sha256: string };
type Approve = (tool: string, command: string, reason: string) => Promise<boolean>;
const hash = (data: Buffer | string) => createHash('sha256').update(data).digest('hex');
export class PracticalTools {
  private readonly previews = new Map<string, { source: string; output: string; entries: Entry[] }>();
  constructor(private readonly files: WorkspaceFiles, private readonly outcomes: OutcomeRepository, private readonly turnId: string,
    private readonly approve: Approve, private readonly active: () => boolean, private readonly signal: AbortSignal) {}
  private preview(args: OrganizeArguments): string {
    const source = this.files.path(args.source), output = this.files.path(args.output);
    if (source === output || output.startsWith(source + '/')) throw Error('输出目录必须在输入目录之外');
    const names = this.files.list(source); if (!names.length) throw Error('目录不能为空');
    let size = 0; const entries: Entry[] = [];
    for (const name of names.sort()) {
      const input = this.files.path(`${source}/${name}`), data = this.files.readBytes(input, 5_000_000);
      size += data.length; if (size > 32_000_000) throw Error('批次超过32MB');
      const extension = extname(name).slice(1).toLowerCase(), category = /^[a-z0-9]{1,12}$/.test(extension) ? extension : 'other';
      entries.push({ source: input, target: this.files.path(`${output}/${category}/${name}`), sha256: hash(data) });
    }
    const id = randomUUID(); this.previews.set(id, { source, output, entries });
    this.outcomes.save(OutcomeSchema.parse({ turn_id: this.turnId, scenario: 'organize', criteria: ['逐文件副本数量与 SHA-256 一致','保留原文件且不覆盖'], reason: '已生成预览，尚未执行' }));
    return JSON.stringify({ preview_id: id, count: entries.length, copies: entries.slice(0, 3), more: Math.max(0, entries.length - 3), scope: '仅本层文件，按扩展名分类' });
  }
  async organize(args: OrganizeArguments): Promise<string> {
    if (!args.preview_id) return this.preview(args);
    const preview = this.previews.get(args.preview_id);
    if (!preview || preview.source !== this.files.path(args.source) || preview.output !== this.files.path(args.output)) throw Error('预览不存在或目录已改变');
    if (!await this.approve('lobuddy_organize', JSON.stringify(preview.entries), '按此清单创建分类副本，保留原文件且不覆盖') || !this.active()) throw Error('整理未获批准或已取消');
    this.outcomes.claimEffect(args.preview_id, this.turnId, JSON.stringify(preview.entries));
    const copied: Entry[] = [];
    try {
      for (const entry of preview.entries) {
        if (!this.active()) throw Error('整理已取消');
        const data = this.files.readBytes(entry.source, 5_000_000);
        if (hash(data) !== entry.sha256) throw Error('源文件自预览后已改变');
        this.files.ensureDirectories(dirname(entry.target)); this.files.writeBytes(entry.target, data, true);
        if (hash(this.files.readBytes(entry.target, 5_000_000)) !== entry.sha256 || hash(this.files.readBytes(entry.source, 5_000_000)) !== entry.sha256) throw Error('复制校验失败');
        copied.push(entry);
      }
    } catch {
      this.outcomes.finishEffect(args.preview_id, 'unknown');
      this.outcomes.save(OutcomeSchema.parse({ turn_id: this.turnId, verdict: 'failed', scenario: 'organize', criteria: ['全部副本与原文件哈希一致','不覆盖'],
        evidence: [...copied, { check: 'copy_integrity', passed: false, copied_count: copied.length }], reason: '整理未完整通过；保留已产生副本，不自动重放' }));
      throw Error('整理未完整通过，不自动重放');
    }
    this.outcomes.finishEffect(args.preview_id, 'completed');
    const outcome = OutcomeSchema.parse({ turn_id: this.turnId, verdict: 'verified', scenario: 'organize',
      criteria: ['副本数量等于预览数量','原文件与副本 SHA-256 一致','独占创建不覆盖'], evidence: copied, reason: `已验证 ${copied.length} 份分类副本` });
    this.outcomes.save(outcome); return JSON.stringify(outcome);
  }
  async digest(args: DigestArguments): Promise<string> {
    const started = performance.now(); let reads = 0, hits = 0;
    const cache = new Map<string, { signature: string; text: string }>();
    const evidence: Outcome['evidence'] = [];
    const sections: Record<'summary' | 'decisions' | 'todos', { source: string; quote: string }[]> = { summary: [], decisions: [], todos: [] };
    for (const [index, source] of args.sources.entries()) {
      if (!this.active()) throw Error('资料归纳已取消');
      let canonical = source;
      try {
        let text: string;
        if (/^https?:\/\//.test(source)) { reads++; text = await fetchPage(source, 12000, this.signal); }
        else {
          canonical = this.files.path(source); const before = this.files.signature(canonical), previous = args.reuse_local_sources ? cache.get(canonical) : undefined;
          if (previous && previous.signature === before) { hits++; text = previous.text; }
          else {
            reads++; text = this.files.read(canonical); const after = this.files.signature(canonical);
            if (before !== after) throw Error('读取期间来源发生变化');
            if (args.reuse_local_sources) cache.set(canonical, { signature: after, text });
          }
        }
        const lines = text.split(/\r?\n/u).map(line => line.trim()).filter(Boolean); if (!lines.length) throw Error('空来源');
        const ref = `S${index + 1}`;
        evidence.push({ source, canonical_source: canonical, ref, sha256: hash(text), available: true });
        sections.summary.push({ source: ref, quote: [...lines.slice(0, 2).join('\n')].slice(0, 800).join('') });
        for (const [key, pattern] of [['decisions', /决定|决议|确定|decision/i], ['todos', /待办|TODO|下一步|需要完成/i]] as const) {
          for (const line of lines) if (pattern.test(line) && sections[key].length < 20) sections[key].push({ source: ref, quote: [...line].slice(0, 800).join('') });
        }
      } catch { evidence.push({ source, available: false }); }
    }
    if (!this.active()) throw Error('资料归纳已取消');
    const complete = evidence.every(item => item.available); evidence.push({ sections });
    const outcome = OutcomeSchema.parse({ turn_id: this.turnId, verdict: complete ? 'verified' : 'unknown', scenario: 'digest',
      metrics: { source_count: args.sources.length, physical_reads: reads, cache_hits: hits, elapsed_ms: performance.now() - started, model_calls: 0, model_tokens: 0 },
      criteria: ['所有输入来源可读取','每个摘录有来源编号且来自原文'], evidence,
      reason: complete ? '来源摘录校验通过；这是摘录式归纳，不保证语义完整性' : '部分来源缺失，未补全推测' });
    this.outcomes.save(outcome); return JSON.stringify({ outcome, sections, mode: '原文摘录；无明确决定/待办时保持空列表' });
  }
}
