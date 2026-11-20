import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, rm, writeFile, readFile, symlink, link, rename, lstat, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { PassThrough } from 'node:stream';
import { EventEmitter } from 'node:events';
import type { IncomingMessage, RequestOptions, request } from 'node:http';
import sharp from 'sharp';
import { OrganizeArgumentsSchema, DigestArgumentsSchema, TurnStateSchema } from '@lobuddy/contracts';
import { WorkspaceFiles } from './tools/files.js';
import { readPrivate } from './storage/files.js';
import { Store } from './storage/database.js';
import { OutcomeRepository } from './storage/outcomes.js';
import { PracticalTools } from './tools/practical.js';
import { ImageStore } from './tools/images.js';
import { LocalOpen } from './tools/local.js';
import { commandArguments, runCommand } from './tools/commands.js';
import { publicAddress, publicIP, pageText, fetchPage, fetchDocument } from './tools/web.js';
import { GovernedTools } from './tools/governed.js';
import { Approvals } from './tasks/approvals.js';
import { runtimeSettings } from './config/settings.js';
import { forbidsCommandExecution } from '@lobuddy/domain';

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'lobuddy-tool-')), workspace = join(root, 'workspace');
  await mkdir(workspace); const files = new WorkspaceFiles(workspace, [join(workspace, 'protected')]);
  return { root, workspace, files, clean: () => rm(root, { recursive: true, force: true }) };
}
test('native workspace access rejects traversal, symlinks, hardlinks, FIFO and changed parents without truncation', async () => {
  const f = await fixture();
  try {
    await writeFile(join(f.root, 'outside'), 'preserve');
    await mkdir(join(f.workspace, 'folder'));
    await mkdir(join(f.workspace, 'protected')); await writeFile(join(f.workspace, 'protected', 'a'), 'protected');
    await writeFile(join(f.workspace, 'folder', '中文.txt'), '你好');
    assert.deepEqual(f.files.list('folder'), ['中文.txt']); assert.equal(f.files.read('folder/中文.txt'), '你好');
    await symlink(f.root, join(f.workspace, 'escape'));
    await link(join(f.root, 'outside'), join(f.workspace, 'hard'));
    for (const path of ['../outside','..\\escape','escape/outside','hard','skills/a','memory/a','.env','.git/config','protected/a','C:/secret','a/../b','nested/../../escape']) {
      assert.throws(() => f.files.read(path), path); assert.throws(() => f.files.write(path, 'bad'), path);
    }
    assert.equal(await readFile(join(f.root, 'outside'), 'utf8'), 'preserve');
    f.files.checkNoSymlink('folder/new');
    await rename(join(f.workspace, 'folder'), join(f.workspace, 'original'));
    await symlink(f.root, join(f.workspace, 'folder'));
    assert.throws(() => f.files.write('folder/new', 'bad'));
    await assert.rejects(lstat(join(f.root, 'new')), { code: 'ENOENT' });
    const fifo = join(f.workspace, 'fifo'); assert.equal(spawnSync('/usr/bin/mkfifo', [fifo]).status, 0);
    assert.throws(() => f.files.read('fifo')); assert.throws(() => f.files.write('fifo', 'bad'));
    await assert.rejects(readPrivate(fifo));
    f.files.write('normal', 'first'); f.files.write('normal', 'short'); assert.equal(f.files.read('normal'), 'short');
    await symlink('unresolvable',join(f.root,'unresolvable'));
    assert.throws(() => new WorkspaceFiles(f.workspace,[join(f.root,'unresolvable')]),/ELOOP/);
    assert.throws(() => f.files.writeBytes('normal', Buffer.from('bad'), true));
    assert.throws(() => f.files.readBytes('normal', 2)); await assert.rejects(readPrivate(join(f.workspace, 'normal'), 2));
  } finally { await f.clean(); }
});
test('organize approves the full preview, verifies copies and refuses replay or overwriting', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  const outcomes = new OutcomeRepository(store); let allowed = false; const approvals: string[] = [];
  const practical = new PracticalTools(f.files, outcomes, 'organize', async (_tool, manifest) => { approvals.push(manifest); return allowed; }, () => true, new AbortController().signal);
  try {
    f.files.createDirectory('source'); f.files.write('source/一.txt', '内容'); f.files.write('source/two.md', '记录');
    const args = OrganizeArgumentsSchema.parse({ source: 'source', output: 'output' });
    const preview = JSON.parse(await practical.organize(args)) as { preview_id: string };
    const execute = { ...args, preview_id: preview.preview_id };
    await assert.rejects(practical.organize(execute)); await assert.rejects(lstat(join(f.workspace, 'output')), { code: 'ENOENT' });
    allowed = true; const result = JSON.parse(await practical.organize(execute)) as { verdict: string };
    assert.equal(result.verdict, 'verified'); assert.equal(JSON.parse(approvals[0]!).length, 2);
    assert.equal(f.files.read('output/txt/一.txt'), f.files.read('source/一.txt'));
    await assert.rejects(practical.organize(execute)); assert.equal(outcomes.get('organize').verdict, 'verified');
    const other = new PracticalTools(f.files, outcomes, 'overwrite', async () => true, () => true, new AbortController().signal);
    const p2 = JSON.parse(await other.organize(args)) as { preview_id: string };
    await assert.rejects(other.organize({ ...args, preview_id: p2.preview_id }));
    assert.equal(outcomes.get('overwrite').verdict, 'failed'); assert.equal(f.files.read('source/一.txt'), '内容');
  } finally { store.close(); await f.clean(); }
});
test('changed preview and cancelled approval cannot copy; digest preserves evidence and marks missing sources unknown', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  const outcomes = new OutcomeRepository(store); let active = true;
  const practical = new PracticalTools(f.files, outcomes, 'changing', async () => true, () => active, new AbortController().signal);
  try {
    f.files.createDirectory('source'); f.files.write('source/a.txt', '旧');
    const args = OrganizeArgumentsSchema.parse({ source: 'source', output: 'output' });
    const preview = JSON.parse(await practical.organize(args)) as { preview_id: string };
    f.files.write('source/a.txt', '新');
    await assert.rejects(practical.organize({ ...args, preview_id: preview.preview_id }));
    await assert.rejects(lstat(join(f.workspace, 'output')), { code: 'ENOENT' });
    active = false; await assert.rejects(practical.organize({ ...args, preview_id: preview.preview_id })); active = true;
    f.files.write('notes.md', '会议记录\n决定：先测试\n待办：补充证据');
    const digest = new PracticalTools(f.files, outcomes, 'digest', async () => false, () => active, new AbortController().signal);
    await digest.digest(DigestArgumentsSchema.parse({ sources: ['notes.md','notes.md','absent'], reuse_local_sources: true }));
    const result = outcomes.get('digest'); assert.equal(result.verdict, 'unknown'); assert.equal(result.metrics.cache_hits, 1);
    assert.equal(result.evidence[0]?.available, true); assert.equal(result.evidence[2]?.available, false);
    assert.match(JSON.stringify(result.evidence), /决定：先测试/);
  } finally { store.close(); await f.clean(); }
});
test('organize rejects unsafe sources before approval and changed output links cannot produce verified evidence', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  const outcomes = new OutcomeRepository(store); let approvals = 0;
  const practical = new PracticalTools(f.files, outcomes, 'symlink', async () => { approvals++; return true; }, () => true, new AbortController().signal);
  try {
    for (const source of ['../input', '.env', 'skills', '/etc']) {
      await assert.rejects(practical.organize(OrganizeArgumentsSchema.parse({ source, output: 'output' })));
    }
    assert.equal(approvals, 0);
    f.files.createDirectory('input'); f.files.write('input/a.txt', 'preserve');
    const args = OrganizeArgumentsSchema.parse({ source: 'input', output: 'output' });
    const preview = JSON.parse(await practical.organize(args)) as { preview_id: string };
    await symlink(join(f.workspace, 'input'), join(f.workspace, 'output'));
    await assert.rejects(practical.organize({ ...args, preview_id: preview.preview_id }));
    assert.equal(outcomes.get('symlink').verdict, 'failed'); assert.equal(f.files.read('input/a.txt'), 'preserve');
    await assert.rejects(lstat(join(f.workspace, 'input/txt')), { code: 'ENOENT' });
    const restarted = new OutcomeRepository(store);
    assert.throws(() => restarted.claimEffect(preview.preview_id, 'symlink', '{}'), /不能自动重放/);
  } finally { store.close(); await f.clean(); }
});
test('digest results cite exact decision and todo sources and never fill missing evidence', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  try {
    f.files.write('notes.md', '决定使用绿色主题\n待办：更新首页\n简短测试材料');
    const practical = new PracticalTools(f.files, new OutcomeRepository(store), 'digest', async () => false, () => true, new AbortController().signal);
    const full = JSON.parse(await practical.digest(DigestArgumentsSchema.parse({ sources: ['notes.md'] })));
    assert.equal(full.outcome.verdict, 'verified');
    assert.deepEqual(full.sections.decisions, [{ source: 'S1', quote: '决定使用绿色主题' }]);
    assert.deepEqual(full.sections.todos, [{ source: 'S1', quote: '待办：更新首页' }]);
    const partial = JSON.parse(await practical.digest(DigestArgumentsSchema.parse({ sources: ['notes.md', 'missing.txt'] })));
    assert.equal(partial.outcome.verdict, 'unknown'); assert.equal(partial.outcome.evidence[1].available, false);
    for (const section of Object.values(partial.sections) as { source: string }[][]) assert.ok(section.every(item => item.source === 'S1'));
  } finally { store.close(); await f.clean(); }
});
test('DNS validation rejects mixed private answers and URL tricks; parsers exclude executable HTML and malformed XML', async () => {
  for (const ip of ['127.0.0.1','10.1.2.3','169.254.169.254','100.64.0.1','::1','::ffff:127.0.0.1','fc00::1','2001:db8::1','2002:7f00:1::']) assert.equal(publicIP(ip), false, ip);
  for (const ip of ['1.1.1.1','8.8.8.8','2606:4700:4700::1111']) assert.equal(publicIP(ip), true, ip);
  for (const url of ['file:///etc/hosts','https://user:secret@example.com','http://2130706433','http://[::1]','https://example.com:8443']) await assert.rejects(publicAddress(url));
  await assert.rejects(publicAddress('https://example.com', async () => [{ address: '1.1.1.1', family: 4 }, { address: '127.0.0.1', family: 4 }]));
  const result = await publicAddress('https://example.com/path', async () => [{ address: '1.1.1.1', family: 4 }]); assert.equal(result.address, '1.1.1.1');
  assert.equal(pageText('<p>Hello<script>secret</script><style>hidden</style> world</p>', 'text/html'), 'Hello world');
  const visible = pageText('<style>secret</style><p>safe</p><a href="javascript:alert(1)">link</a><a href="https://example.org">source</a>','text/html');
  assert.doesNotMatch(visible,/secret|javascript|alert/); assert.match(visible,/safe/); assert.match(visible,/https:\/\/example.org/);
  assert.match(pageText('<rss><channel><item><title>标题</title><link>https://example.com</link><description>来源</description></item></channel></rss>', 'application/rss+xml'), /标题\nhttps:\/\/example.com\n来源/);
  for (const xml of ['<!DOCTYPE rss><rss/>','<rss><item><title>broken</item></rss>']) assert.throws(() => pageText(xml, 'text/xml'));
});
test('image import validates bytes, keeps IDs and detects changed content; local opening requires unchanged resolved candidate', async () => {
  const f = await fixture(); const images = new ImageStore(join(f.root, 'images'));
  try {
    const png = await sharp({ create: { width: 16, height: 12, channels: 3, background: '#448888' } }).png().toBuffer();
    const first = await images.importBytes(png, '.png'); assert.equal(first.width, 16); assert.equal((await images.importBytes(png, '.png')).image_id, first.image_id);
    await assert.rejects(images.importBytes(png, '.jpg')); await assert.rejects(images.importBytes(Buffer.from('not an image'), '.png'));
    await writeFile(join(f.root, 'images', first.image_id), 'changed'); await assert.rejects(images.get(first.image_id));
    const path = join(await realpath(f.workspace), '独特候选测试.txt'); await writeFile(path, 'original');
    const local = new LocalOpen(f.workspace, join(f.root, 'home')); assert.equal(local.resolve('独特候选测试')[0]?.path, path);
    assert.equal(local.validate(path), path); await rename(path, path + '.old'); await writeFile(path, 'replacement'); assert.throws(() => local.validate(path));
    assert.throws(() => local.validate('/Applications/unknown.app'));
  } finally { await f.clean(); }
});
test('web transport pins the validated address, checks each redirect and caps the actual response stream', async () => {
  let requests = 0, mode = 'redirect';
  const transport = ((_url: URL, options: RequestOptions, callback: (response: IncomingMessage) => void) => {
    requests++; assert.equal(options.agent, false); assert.ok(options.lookup);
    options.lookup('example.com', { all: false }, (error, address) => { assert.equal(error, null); assert.equal(address, '1.1.1.1'); });
    const req = new EventEmitter() as EventEmitter & { end: () => void };
    req.end = () => {
      const response = new PassThrough() as unknown as IncomingMessage;
      response.statusCode = mode === 'redirect' ? 302 : 200;
      response.headers = mode === 'redirect' ? { location: 'http://127.0.0.1/private' } : { 'content-type': mode === 'html' ? 'text/html' : mode === 'json' ? 'application/json' : 'text/plain' };
      callback(response);
      (response as unknown as PassThrough).end(mode === 'oversize' ? Buffer.alloc(512001) : mode === 'html' ? '<p>visible</p><script>hidden</script><a href="https://example.org">source</a>' + '字'.repeat(300) : mode === 'json' ? '{"release":"v1"}' : 'source');
    };
    return req;
  }) as typeof request;
  const network = { lookup: async () => [{ address: '1.1.1.1', family: 4 }], request: transport };
  const signal = new AbortController().signal;
  await assert.rejects(fetchPage('https://example.com', 1000, signal, network), /非公网/); assert.equal(requests, 1);
  mode = 'oversize'; await assert.rejects(fetchPage('https://example.com', 1000, signal, network), /上限/);
  mode = 'normal'; assert.match(await fetchPage('https://example.com', 1000, signal, network), /网页来源：https:\/\/example.com\/\n/);
  mode = 'html'; const bounded = await fetchPage('https://example.com',200,signal,network);
  assert.ok([...bounded].length <= 200); assert.match(bounded,/visible/); assert.match(bounded,/https:\/\/example.org/); assert.doesNotMatch(bounded,/hidden/);
  mode = 'json'; assert.deepEqual(await fetchDocument('https://example.com',signal,network),{
    url: 'https://example.com/',text: '{"release":"v1"}',contentType: 'application/json',
  });
  mode = 'redirect'; await assert.rejects(fetchDocument('https://example.com',signal,network),/非公网/);
});
test('web cancellation also bounds a pending DNS lookup before any socket opens', { timeout: 1000 },async () => {
  const abort = new AbortController(); let requests = 0;
  const pending = fetchDocument('https://example.com',abort.signal,{
    lookup: () => new Promise(() => {}),request: (() => { requests++; throw Error('unexpected socket'); }) as typeof request,
  });
  abort.abort(); await assert.rejects(pending,/已取消/); assert.equal(requests,0);
});
test('command parsing restricts flags, paths and shell grammar; subprocess output is bounded and cancellation is explicit', async () => {
  const f = await fixture();
  try {
    assert.deepEqual(commandArguments('echo "hello world"', f.files).slice(1), ['hello world']);
    assert.deepEqual(commandArguments('echo "a\\q"', f.files).slice(1), ['a\\q']);
    for (const command of ['sh -c whoami','echo a; ls','cat ../secret','rm -rf .','cat .env','echo $(pwd)','cat "unterminated',
      'echo ok; rm a','find . -exec cat .env ;','python3 script.py','curl https://example.com','git -c core.pager=malicious log','ls -R','cp -r a b']) assert.throws(() => commandArguments(command, f.files), command);
    const result = await runCommand(commandArguments('echo 你好世界', f.files), f.workspace, 2, 1000, new AbortController().signal);
    assert.match(result, /退出码 0\n你好/); assert.ok(!result.includes('世界'));
    const abort = new AbortController(); abort.abort(); await assert.rejects(runCommand(commandArguments('pwd', f.files), f.workspace, 100, 1000, abort.signal));
    const fifo = join(f.workspace, 'blocked'); assert.equal(spawnSync('/usr/bin/mkfifo', [fifo]).status, 0);
    const controller = new AbortController(), start = Date.now();
    const task = runCommand(['/bin/cat', fifo], f.workspace, 100, 30000, controller.signal);
    const timer = setTimeout(() => controller.abort(), 30);
    try { await assert.rejects(task); assert.ok(Date.now() - start < 1000); } finally { clearTimeout(timer); }
  } finally { await f.clean(); }
});
test('legacy forbidden command grammar and delete wildcards are rejected before approval without effects', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  let approvalCount = 0;
  const approvals = new Approvals(() => { approvalCount++; });
  const settings = runtimeSettings({ data: join(f.root, 'data'), workspace: f.workspace, logs: join(f.root, 'logs') });
  settings.shell_enabled = true;
  const state = TurnStateSchema.parse({ turn_id: 'legacy-risk', task_id: 'task', session_id: 's', engine_id: 'engine', input_text: '删除工作区临时文件', lane: 'foreground', status: 'running' });
  try {
    const blocked = [
      'rm *.tmp', 'rm file?.txt', 'rm [abc].txt', 'rm "*.tmp"', 'rm -r src/*.pyc', 'del *.log',
      'format C:', 'mkfs.ext4 /dev/sda', 'shutdown -h now', 'reboot',
      'rm -fr /', 'rm   -rf   /', 'del /f file.txt', 'del  /s  /q  file', 'rd /s folder', 'rd /s /q folder',
      'dd if=/dev/zero of=/dev/sda', ':(){ :|:& };:', 'invoke-expression', 'iex("do-something")', 'iex ("do-something")', 'iex  (123)',
      'pushd /tmp', 'popd', 'cd /tmp', 'echo safe || rm temp.txt',
      'git --git-dir=/tmp status', 'git --work-tree=/tmp status', 'git --exec-path=/tmp status',
      'git --config-env=alias.x=ENV status', 'git -c alias.pwn="!echo X" status', 'git -C/tmp status', 'git -ccore.worktree=/tmp status',
      'git config alias.pwn !echo', 'git pwn', 'git pull', 'git clean -fdx', 'git diff --output=/tmp/x', 'git diff --output /tmp/x',
      'git diff -o../../x', 'git diff --out=../../x', 'git diff --no-index a b', 'git diff --ext-diff', 'git diff --ext', 'git diff --pat',
      'git diff -po../../x', 'git diff -Rpo../../x', 'git diff -pR', 'git diff -Rp', 'git log -Sfoo',
      'echo ok && rm temp.txt', 'ls; rm temp.txt', 'cat file | rm temp.txt', 'echo data > file.txt',
      'python -c "print(1)"', 'node -e "console.log(1)"', 'powershell -enc abc', 'pwsh -EncodedCommand abc',
      '', '   ', 'unknown_cmd arg1', 'ls\nrm temp.txt', 'rm /etc/passwd', 'rm -rf /',
      'python script.py', 'git status', 'ping 127.0.0.1', 'hello', 'rm -r temp_dir', 'rm -rf workspace/cache',
      'rm E:\\GitHub\\Repositories\\Lobuddy\\temp\\a.txt', 'del temp.txt', 'del /q temp.txt', 'rmdir /s temp_dir',
      'powershell -NoProfile -Command Remove-Item -LiteralPath "temp.txt" -Force',
      'pwsh -NoProfile -Command Remove-Item -LiteralPath "temp.txt" -Force', 'rm -rf C:\\',
      'dir /s; where /R foo*', 'dir /s | findstr foo', 'cmd1 && cmd2',
      'where /R "%USERPROFILE%\\Desktop" 洛克* 2>nul & dir /s /b "%USERPROFILE%\\Desktop\\*洛克*" 2>nul',
    ];
    // Even a literal filename containing '*' must not bypass the old delete policy.
    await writeFile(join(f.workspace, '*.tmp'), 'preserve');
    for (const [index, command] of blocked.entries()) {
      assert.throws(() => commandArguments(command, f.files), command);
      const tools = new GovernedTools(state, settings, approvals, new OutcomeRepository(store), new AbortController().signal, () => true, join(f.root, 'app'));
      await assert.rejects(tools.execute({ callId: `blocked-${index}`, name: 'lobuddy_exec', arguments: { command } }), command);
    }
    assert.equal(approvalCount, 0); assert.deepEqual(approvals.list(), []);
    assert.equal(await readFile(join(f.workspace, '*.tmp'), 'utf8'), 'preserve');
    assert.equal(commandArguments('rm temp.txt', f.files).at(-1), 'temp.txt');
    assert.equal(commandArguments('ls -la', f.files).at(-1), '-la');
    assert.equal(commandArguments('cat README.md', f.files).at(-1), 'README.md');
    assert.deepEqual(commandArguments('echo hello world', f.files).slice(1), ['hello', 'world']);
    assert.equal(commandArguments('mkdir new_dir', f.files).at(-1), 'new_dir');
    assert.equal(commandArguments('rm', f.files).length, 1);
  } finally { store.close(); await f.clean(); }
});
test('governance rejects unmapped tools, enforces read budgets and keeps command approval and intent boundaries', async () => {
  const f = await fixture(), store = new Store(join(f.root, 'database'), { create: true });
  let approved = false, count = 0;
  const approvals = new Approvals((_state, _kind, data) => { count++; approvals.resolve(data.approval_id!, approved); });
  const settings = runtimeSettings({ data: join(f.root, 'data'), workspace: f.workspace, logs: join(f.root, 'logs') });
  const state = TurnStateSchema.parse({ turn_id: 't', task_id: 'task', session_id: 's', engine_id: 'engine', input_text: '创建文件', lane: 'foreground', status: 'running' });
  const make = () => new GovernedTools(state, settings, approvals, new OutcomeRepository(store), new AbortController().signal, () => true, join(f.root, 'app'));
  try {
    f.files.write('read.txt', '内容'); settings.execution_max_tool_calls_per_task = 2;
    const limited = make();
    await assert.rejects(limited.execute({ callId: 'invalid', name: 'exec', arguments: {} }));
    for (const args of [null, 'rm -rf /', [], 1, { path: 'read.txt', unexpected: 'field' }]) {
      await assert.rejects(limited.execute({ callId: 'invalid-args', name: 'lobuddy_read_file', arguments: args }));
    }
    for (let i = 0; i < 2; i++) assert.equal(await limited.execute({ callId: String(i), name: 'lobuddy_read_file', arguments: { path: 'read.txt' } }), '内容');
    await assert.rejects(limited.execute({ callId: 'third', name: 'lobuddy_write_file', arguments: { path: 'result', content: 'bad' } }));
    assert.equal(count, 0);
    settings.shell_enabled = true;
    const command = { callId: 'command', name: 'lobuddy_exec', arguments: { command: 'touch created.txt' } };
    await assert.rejects(make().execute(command)); await assert.rejects(lstat(join(f.workspace, 'created.txt')), { code: 'ENOENT' });
    approved = true; await make().execute(command); assert.ok((await lstat(join(f.workspace, 'created.txt'))).isFile());
    assert.equal(count, 2);
    await symlink(join(f.workspace, 'read.txt'), join(f.workspace, 'linked'));
    await assert.rejects(make().execute({ ...command, arguments: { command: 'cat linked' } })); assert.equal(count, 2);
    for (const prompt of ['帮我打开桌面应用','查找最近的文档在哪里','帮我找项目','搜索文件图片','帮我打开桌面的洛克王国：世界','打开微信','帮我启动桌面上的 QQ','帮我打开「洛克王国：世界」']) {
      assert.equal(forbidsCommandExecution(prompt), true, prompt); state.input_text = prompt;
      await assert.rejects(make().execute(command));
    }
    assert.equal(count, 2);
    for (const prompt of ['请整理这些文本','讲个笑话','我是谁','','   ']) assert.equal(forbidsCommandExecution(prompt), false);
  } finally { store.close(); await f.clean(); }
});

test('governed writes fail closed on missing approval, wrong identity, cancellation and a parent replaced while approval is pending', async () => {
  for (const mode of ['deny','wrong','timeout','cancel','delivery-error','symlink']) {
    const f = await fixture(), store = new Store(join(f.root,'database'),{ create: true });
    const state = TurnStateSchema.parse({ turn_id: mode,task_id: mode,session_id: 's',engine_id: 'e',lane: 'foreground',status: 'running',input_text: '写入结果' });
    const settings = runtimeSettings({ data: join(f.root,'data'),workspace: f.workspace,logs: join(f.root,'logs') });
    settings.hitl_approval_timeout_seconds = 1;
    let ready!: () => void; const requested = new Promise<void>(resolve => { ready = resolve; });
    const approvals = new Approvals(() => { if (mode === 'delivery-error') throw Error('synthetic delivery failure'); ready(); });
    const owner = new AbortController();
    try {
      await mkdir(join(f.workspace,'nested')); await mkdir(join(f.root,'outside'));
      await writeFile(join(f.root,'outside/result.txt'),'preserve');
      const tools = new GovernedTools(state,settings,approvals,new OutcomeRepository(store),owner.signal,() => !owner.signal.aborted,join(f.root,'app'));
      const executing = tools.execute({ callId: 'write',name: 'lobuddy_write_file',arguments: { path: 'nested/result.txt',content: 'new' } });
      const rejected = assert.rejects(executing);
      if (mode !== 'delivery-error') {
        await requested; const id = approvals.list()[0]!.approval_id;
        if (mode === 'deny') approvals.resolve(id,false);
        if (mode === 'wrong') assert.equal(approvals.resolve('not-the-id',true),false);
        if (mode === 'cancel') owner.abort();
        if (mode === 'symlink') {
          await rm(join(f.workspace,'nested'),{ recursive: true }); await symlink(join(f.root,'outside'),join(f.workspace,'nested'));
          approvals.resolve(id,true);
        }
      }
      await rejected; assert.deepEqual(approvals.list(),[]);
      assert.equal(await readFile(join(f.root,'outside/result.txt'),'utf8'),'preserve');
      if (mode !== 'symlink') await assert.rejects(lstat(join(f.workspace,'nested/result.txt')),{ code: 'ENOENT' });
    } finally { approvals.deny(); store.close(); await f.clean(); }
  }
});
