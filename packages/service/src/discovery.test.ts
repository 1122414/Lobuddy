import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { DiscoveryPolicySchema, DiscoveryStateSchema } from '@lobuddy/contracts';
import { Store } from './storage/database.js';
import { Preferences } from './storage/preferences.js';
import { PublicDiscovery, releaseItems } from './companion/discovery.js';
const release = (now: number, extra = {}) => ({ id: 1,tag_name: 'v1.0',name: '新版声音创作工具',body: '公开发布说明',
  published_at: new Date((now - 3600) * 1000).toISOString(),draft: false,prerelease: false,...extra });
const document = (rows: unknown) => ({ url: 'https://api.github.com/repos/a/b/releases',contentType: 'application/json',text: JSON.stringify(rows) });
async function fixture() {
  const root = await mkdtemp(join(tmpdir(),'lobuddy-discovery-')), path = join(root,'lobuddy.db');
  let now = new Date(2026,9,30,0,15).getTime() / 1000, quiet = false, calls = 0;
  const store = new Store(path,{ create: true });
  let fetcher = async (_url: string,_signal: AbortSignal) => document([release(now)]);
  const create = () => new PublicDiscovery(store,() => quiet,() => now,async (url,signal) => {
    calls++; assert.match(url,/^https:\/\/api\.github\.com\/repos\/[a-z0-9_.-]+\/[a-z0-9_.-]+\/releases\?per_page=3$/u);
    return fetcher(url,signal);
  });
  const discovery = create();
  const enable = (service = discovery) => service.configure(crypto.randomUUID(),DiscoveryPolicySchema.parse({
    ...service.view().policy,enabled: true,interests: ['AI 陪伴'],repositories: ['a/b'],
  }));
  return { root,path,store,discovery,create,enable,now: () => now,calls: () => calls,
    advance: (seconds: number) => { now += seconds; },quiet: (value: boolean) => { quiet = value; },
    fetch: (fn: typeof fetcher) => { fetcher = fn; },
    close: async () => { await discovery.close(); store.close(); await rm(root,{ recursive: true,force: true }); } };
}

test('release cache admits only fresh published stable releases, deduplicates identity and constructs official links', () => {
  const now = Date.now() / 1000;
  const rows = [release(now),release(now,{ name: '更新后的标题' }),release(now,{id: 2,draft: true}),release(now,{id: 3,prerelease: true}),
    release(now,{id: 4,published_at: null}),release(now,{id: 5,published_at: new Date((now + 1) * 1000).toISOString()}),
    release(now,{id: 6,published_at: new Date((now - 7 * 86400) * 1000).toISOString()}),release(now,{id: 7,published_at: 'not-a-date'}),
    release(now,{id: 8,published_at: null,updated_at: new Date(now * 1000).toISOString()}),
    release(now,{id: 9,html_url: 'http://127.0.0.1/private',tag_name: 'v1/branch',body: '<script>execute()</script><p>文字</p>'})];
  const items = releaseItems('a/b',document(rows),now);
  assert.equal(items.length,2); assert.equal(items[0]!.title,'更新后的标题');
  assert.equal(items[1]!.url,'https://github.com/a/b/releases/tag/v1%2Fbranch'); assert.equal(items[1]!.text,'文字');
  assert.ok(items.every(item => item.expires_at === item.published_at + 7 * 86400));
  assert.equal(releaseItems('a/b',document([release(now,{body: '字'.repeat(500001)})]),now).length,0);
  assert.throws(() => releaseItems('a/b',document(Array(31).fill(release(now))),now));
  assert.throws(() => releaseItems('a/b',{ ...document(rows),contentType: 'text/html' },now));
});

test('public discovery defaults off, respects quiet state, single ownership and durable refresh intervals', async () => {
  const f = await fixture();
  try {
    assert.equal(await f.discovery.tick(),false); assert.equal(f.calls(),0); f.enable();
    f.quiet(true); await f.discovery.tick(); assert.equal(f.calls(),0); f.quiet(false);
    const first = f.discovery.tick(); assert.equal(f.discovery.tick(),first); await first;
    assert.equal(f.calls(),1); assert.equal(f.discovery.view().items.length,1); assert.equal(f.discovery.view().used,1);
    await f.discovery.refresh(); assert.equal(f.calls(),1);
    const restarted = f.create(); await restarted.tick(); assert.equal(f.calls(),1);
    f.advance(12 * 3600); await restarted.tick(); assert.equal(f.calls(),2); assert.equal(restarted.view().items.length,1);
    assert.equal(f.store.connection.prepare('SELECT count(*) AS n FROM memory_item').get()!.n,0);
    await restarted.close();
  } finally { await f.close(); }
});

test('an explicit refresh may read while quiet but cannot bypass sleep, source intervals or daily allowance', async () => {
  const f = await fixture();
  try {
    f.enable(); f.quiet(true); f.discovery.power(true); await f.discovery.refresh(); assert.equal(f.calls(),0);
    f.discovery.power(false); await f.discovery.refresh(); assert.equal(f.calls(),1);
    await f.discovery.refresh(); assert.equal(f.calls(),1); assert.equal(f.discovery.view().used,1);
  } finally { await f.close(); }
});

test('manual refresh acknowledges before slow IO and overlapping requests share one bounded batch', async () => {
  const f = await fixture();
  try {
    f.discovery.configure('sources',DiscoveryPolicySchema.parse({ enabled: true,interests: ['AI'],repositories: ['a/b','c/d','e/f'] }));
    let finish!: () => void;
    f.fetch(async () => { await new Promise<void>(resolve => { finish = resolve; }); return document([release(f.now())]); });
    const accepted = f.discovery.requestRefresh(); assert.equal(accepted.reading,true); assert.equal(accepted.used,1);
    const complete = f.discovery.refresh(); assert.equal(f.discovery.refresh(),complete);
    for (let n = 0; n < 3; n++) {
      while (f.calls() < n + 1) await new Promise(resolve => setImmediate(resolve));
      assert.equal(f.discovery.requestRefresh().used,n + 1); finish();
    }
    const result = await complete;
    assert.equal(f.calls(),3); assert.equal(result.reading,false); assert.equal(result.items.length,3);
    await f.discovery.refresh(); assert.equal(f.calls(),3);
  } finally { await f.close(); }
});

test('foreground activity cancels the remaining manual batch instead of starting the next source', async () => {
  const f = await fixture();
  try {
    f.discovery.configure('sources',DiscoveryPolicySchema.parse({ enabled: true,interests: ['AI'],repositories: ['a/b','c/d'] }));
    let finish!: () => void;
    f.fetch(async () => { await new Promise<void>(resolve => { finish = resolve; }); return document([release(f.now())]); });
    f.discovery.requestRefresh(); const complete = f.discovery.refresh(); await Promise.resolve();
    f.discovery.activity(); finish(); await complete;
    assert.equal(f.calls(),1); assert.equal(f.discovery.view().items.length,0); assert.equal(f.discovery.view().reading,false);
  } finally { await f.close(); }
});

test('manual refresh survives ambient typing heartbeats while automatic reads still yield', async () => {
  const f = await fixture();
  try {
    f.enable(); let finish!: () => void, signal!: AbortSignal;
    f.fetch(async (_url,current) => { signal = current; await new Promise<void>(resolve => { finish = resolve; }); return document([release(f.now())]); });
    const manual = f.discovery.refresh(); await Promise.resolve();
    f.discovery.activity('ambient'); assert.equal(signal.aborted,false); finish();
    const ready = await manual; assert.equal(ready.items.length,1); const checkedAt = ready.items[0]!.checked_at;
    f.advance(12 * 3600); const automatic = f.discovery.tick(); await Promise.resolve();
    f.discovery.activity('ambient'); assert.equal(signal.aborted,true); finish(); await automatic;
    assert.equal(f.discovery.view().items[0]!.checked_at,checkedAt);
    assert.equal(f.discovery.view().attempts[0]!.status,'interrupted');
  } finally { await f.close(); }
});

test('failed reads retain their budget and backoff across reconfiguration, restart and a backward clock', async () => {
  const f = await fixture();
  try {
    f.enable(); f.fetch(async () => { throw Error('private provider detail must never be returned'); });
    for (let n = 0; n < 6; n++) { await f.discovery.tick(); f.advance(2 * 3600); }
    assert.equal(f.calls(),6); assert.equal(f.discovery.view().used,6);
    assert.doesNotMatch(JSON.stringify(f.discovery.view()),/private provider/); assert.equal(f.discovery.view().attempts[0]!.status,'unavailable');
    f.enable(); await f.discovery.refresh(); const restarted = f.create(); await restarted.tick(); assert.equal(f.calls(),6);
    f.advance(-86400); await restarted.tick(); assert.equal(f.calls(),6); assert.equal(restarted.view().used,6);
    f.advance(2 * 86400); await restarted.tick(); assert.equal(f.calls(),7); assert.equal(restarted.view().used,1); await restarted.close();
  } finally { await f.close(); }
});

test('configuration revocation cancels a late result and replay cannot restore a removed source', async () => {
  const f = await fixture();
  try {
    const policy = DiscoveryPolicySchema.parse({enabled: true,interests: ['AI'],repositories: ['a/b']});
    f.discovery.configure('first',policy);
    let finish!: () => void, signal!: AbortSignal;
    f.fetch(async (_url,s) => { signal = s; await new Promise<void>(resolve => { finish = resolve; }); return document([release(f.now())]); });
    const pending = f.discovery.tick(); await Promise.resolve();
    const disabled = { ...f.discovery.view().policy,enabled: false,repositories: [],interests: [] };
    f.discovery.configure('remove',disabled); assert.equal(signal.aborted,true); finish(); await pending;
    assert.equal(f.discovery.view().items.length,0); assert.equal(f.discovery.view().used,1);
    assert.deepEqual(f.discovery.configure('remove',disabled),f.discovery.view());
    assert.throws(() => f.discovery.configure('first',policy),/已更新/);
    assert.throws(() => f.discovery.configure('remove',{ ...disabled,interests: ['changed'] }),/不一致/);
    f.enable(); await f.discovery.tick(); assert.equal(f.calls(),1,'removing and re-adding cannot reset the source interval');
  } finally { await f.close(); }
});

test('sleep and foreground activity discard late data without resetting the reserved attempt', async () => {
  for (const action of ['sleep','activity'] as const) {
    const f = await fixture();
    try {
      f.enable(); let finish!: () => void;
      f.fetch(async () => { await new Promise<void>(resolve => { finish = resolve; }); return document([release(f.now())]); });
      const pending = f.discovery.tick(); await Promise.resolve();
      if (action === 'sleep') f.discovery.power(true); else f.discovery.activity();
      finish(); await pending; assert.equal(f.discovery.view().items.length,0); assert.equal(f.discovery.view().used,1);
      assert.equal(f.discovery.view().attempts[0]!.status,'interrupted');
      f.discovery.power(false); await f.discovery.tick(); assert.equal(f.calls(),1);
    } finally { await f.close(); }
  }
});

test('interrupted persisted reads recover conservatively and expired snapshots are never visible', async () => {
  const f = await fixture();
  try {
    const policy = f.enable().policy, item = releaseItems('a/b',document([release(f.now())]),f.now())[0]!;
    new Preferences(f.store).set('public_discovery',JSON.stringify(DiscoveryStateSchema.parse({ policy,used: 1,day: '2026-10-30',items: [item],
      attempts: [{ repository: 'a/b',at: f.now(),next_at: f.now() + 7200,status: 'reading' }] })));
    const restarted = f.create(); assert.equal(restarted.view().attempts[0]!.status,'interrupted'); await restarted.tick(); assert.equal(f.calls(),0);
    f.advance(7 * 86400); assert.equal(restarted.view().items.length,0); await restarted.close();
  } finally { await f.close(); }
});

test('a failed durable reservation stops discovery before any network request', async () => {
  const f = await fixture();
  try {
    f.enable(); const run = f.store.run.bind(f.store);
    f.store.run = () => { throw Error('synthetic persistence failure'); };
    assert.throws(() => f.discovery.tick(),/persistence failure/); assert.equal(f.calls(),0);
    f.store.run = run; await f.discovery.tick(); assert.equal(f.calls(),0);
    assert.throws(() => f.discovery.requestRefresh(),/已停止/);
    assert.throws(() => f.enable(),/已停止/);
  } finally { await f.close(); }
});
