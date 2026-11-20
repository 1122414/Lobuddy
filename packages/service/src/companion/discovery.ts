import { createHash } from 'node:crypto';
import { z } from 'zod';
import { DiscoveryItemSchema, DiscoveryPolicySchema, DiscoveryStateSchema, DiscoveryViewSchema,
  type DiscoveryItem, type DiscoveryPolicy, type DiscoveryView } from '@lobuddy/contracts';
import { codepointSlice, SECRETS } from '@lobuddy/domain';
import { Store } from '../storage/database.js';
import { Preferences } from '../storage/preferences.js';
import { fetchDocument, pageText } from '../tools/web.js';

const DAY = 86400, MAX_AGE = 7 * DAY;
const hash = (value: string) => createHash('sha256').update(value).digest('hex');
const releaseSchema = z.object({
  id: z.number().int().safe().positive(),tag_name: z.string().min(1).max(200),name: z.string().max(1000).nullable(),
  body: z.string().max(500000).nullable(),published_at: z.iso.datetime().nullable(),draft: z.boolean(),prerelease: z.boolean(),
});
type Document = Awaited<ReturnType<typeof fetchDocument>>;
type Fetch = (url: string, signal: AbortSignal) => Promise<Document>;
export function releaseItems(repository: string, document: Document, now: number): DiscoveryItem[] {
  if (!document.contentType.includes('application/json')) throw Error('发布来源格式无效');
  const rows: unknown = JSON.parse(document.text);
  if (!Array.isArray(rows) || rows.length > 30) throw Error('发布来源格式无效');
  const items = new Map<string,DiscoveryItem>();
  for (const row of rows) {
    const parsed = releaseSchema.safeParse(row); if (!parsed.success) continue;
    const value = parsed.data, published = value.published_at ? Date.parse(value.published_at) / 1000 : NaN;
    if (value.draft || value.prerelease || !Number.isFinite(published) || published > now || published + MAX_AGE <= now) continue;
    const title = codepointSlice((value.name || value.tag_name).trim(),200);
    const text = codepointSlice(pageText(value.body ?? '','text/html'),1800);
    if (!title || SECRETS.test(title + text)) continue;
    const item = DiscoveryItemSchema.safeParse({ id: hash(`${repository}:${value.id}`),repository,title,text,
      url: `https://github.com/${repository}/releases/tag/${encodeURIComponent(value.tag_name)}`,
      published_at: published,checked_at: now,expires_at: published + MAX_AGE });
    if (item.success) items.set(item.data.id,item.data);
  }
  return [...items.values()].sort((a,b) => b.published_at - a.published_at).slice(0,5);
}

// Public release snapshots are a bounded cache, never user memories or execution instructions.
export class PublicDiscovery {
  private readonly preferences: Preferences;
  private state: z.infer<typeof DiscoveryStateSchema>;
  private current?: { abort: AbortController; promise: Promise<boolean> };
  private refreshing?: Promise<DiscoveryView>;
  private activityEpoch = 0;
  private closed = false;
  private suspended = false;
  constructor(store: Store, private readonly quiet: () => boolean, readonly clock = () => Date.now() / 1000,
    private readonly fetch: Fetch = fetchDocument) {
    this.preferences = new Preferences(store);
    this.state = DiscoveryStateSchema.parse(this.preferences.json('public_discovery'));
    let recovered = false;
    for (const attempt of this.state.attempts) if (attempt.status === 'reading') { attempt.status = 'interrupted'; recovered = true; }
    if (recovered) this.save();
  }
  private day(): string {
    const date = new Date(this.clock() * 1000);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
  }
  private save(): void {
    try { this.preferences.set('public_discovery',JSON.stringify(DiscoveryStateSchema.parse(this.state))); }
    catch (error) { this.closed = true; this.current?.abort.abort(); throw error; }
  }
  view(): DiscoveryView {
    const now = this.clock(), policy = this.state.policy;
    return DiscoveryViewSchema.parse({ policy,
      items: policy.enabled ? this.state.items.filter(item => policy.repositories.includes(item.repository) && item.expires_at > now && item.published_at <= now) : [],
      attempts: this.state.attempts.filter(item => policy.repositories.includes(item.repository)),
      used: this.day() > this.state.day ? 0 : this.state.used,daily_limit: 6,reading: !!this.current || !!this.refreshing });
  }
  configure(requestId: string, input: DiscoveryPolicy): DiscoveryView {
    if (this.closed) throw Error('资讯发现已停止，请重新打开应用后重试');
    const policy = DiscoveryPolicySchema.parse(input), fingerprint = hash(JSON.stringify(policy));
    if (SECRETS.test(policy.interests.join('\n'))) throw Error('兴趣中包含秘密信息，请移除后再保存');
    if (requestId === this.state.last_request) {
      if (fingerprint !== this.state.last_fingerprint) throw Error('请求内容与原操作不一致');
      return this.view();
    }
    if (policy.revision !== this.state.policy.revision) throw Error('兴趣来源已更新，请重新打开后再修改');
    this.activity();
    this.state.policy = { ...policy,revision: policy.revision + 1 };
    this.state.items = []; // A changed configuration never silently reuses the old selected sources.
    this.state.last_request = requestId; this.state.last_fingerprint = fingerprint;
    this.save(); return this.view();
  }
  activity(kind: 'ambient' | 'foreground' = 'foreground'): void {
    // Periodic typing heartbeats may describe edits made before an explicit refresh.
    if (kind === 'ambient' && this.refreshing) return;
    this.activityEpoch++; this.current?.abort.abort();
  }
  power(suspended: boolean): void { this.suspended = suspended; if (suspended) this.activity(); }
  tick(manual = false): Promise<boolean> {
    if (this.current) return this.current.promise;
    if (this.closed || this.suspended || !this.state.policy.enabled || !manual && this.quiet()) return Promise.resolve(false);
    const now = this.clock(), day = this.day();
    if (day > this.state.day) { this.state.day = day; this.state.used = 0; }
    if (this.state.used >= 6) return Promise.resolve(false);
    const repository = this.state.policy.repositories.find(repo => !this.state.attempts.some(item => item.repository === repo && item.next_at > now));
    if (!repository) return Promise.resolve(false);
    this.state.attempts = this.state.attempts.filter(item => item.repository !== repository && (item.next_at > now || this.state.policy.repositories.includes(item.repository)));
    if (this.state.attempts.length >= 30) return Promise.resolve(false);
    const attempt = { repository,at: now,next_at: now + 2 * 3600,status: 'reading' as const };
    this.state.attempts.push(attempt); this.state.used++; this.save();
    const abort = new AbortController(), revision = this.state.policy.revision;
    const promise = Promise.resolve().then(() => this.read(repository,revision,abort.signal)).finally(() => { this.current = undefined; });
    this.current = { abort,promise }; return promise;
  }
  private async read(repository: string, revision: number, signal: AbortSignal): Promise<boolean> {
    const current = () => !signal.aborted && !this.closed && !this.suspended && this.state.policy.enabled && this.state.policy.revision === revision;
    const attempt = this.state.attempts.find(item => item.repository === repository)!;
    try {
      signal.throwIfAborted();
      const document = await this.fetch(`https://api.github.com/repos/${repository}/releases?per_page=3`,signal);
      if (!current()) return false;
      const items = releaseItems(repository,document,this.clock());
      this.state.items = [...this.state.items.filter(item => item.repository !== repository && item.expires_at > this.clock()),...items]
        .sort((a,b) => b.published_at - a.published_at).slice(0,30);
      attempt.status = items.length ? 'ready' : 'empty'; attempt.next_at = this.clock() + 12 * 3600;
      return true;
    } catch {
      attempt.status = signal.aborted ? 'interrupted' : 'unavailable';
      return false;
    } finally {
      if (attempt.status === 'reading') attempt.status = 'interrupted';
      // The reserved attempt survives cancellation, configuration changes and process restarts.
      if (!this.closed) this.save();
    }
  }
  requestRefresh(): DiscoveryView {
    if (this.closed) throw Error('资讯发现已停止，请重新打开应用后重试');
    void this.refresh().catch(() => {});
    return this.view();
  }
  refresh(): Promise<DiscoveryView> {
    if (this.refreshing) return this.refreshing;
    const epoch = this.activityEpoch, count = this.state.policy.repositories.length;
    const run = async () => {
      for (let n = 0; n < count; n++) {
        if (this.closed || this.suspended || !this.state.policy.enabled || epoch !== this.activityEpoch) break;
        await this.tick(true);
      }
    };
    this.refreshing = run().then(() => { this.refreshing = undefined; return this.view(); },error => {
      this.refreshing = undefined; throw error;
    });
    return this.refreshing;
  }
  async close(): Promise<void> { this.closed = true; this.activity(); await (this.refreshing ?? this.current?.promise); }
}
