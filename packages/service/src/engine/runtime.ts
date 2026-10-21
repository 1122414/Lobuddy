import { DeepSeekHarness } from '@deepseek-ai/dsh-sdk-client';
import { mkdir, mkdtemp, chmod, lstat, rm } from 'node:fs/promises';
import { join, resolve, isAbsolute } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { BridgeReadySchema, type BridgeEvent } from '@lobuddy/contracts';
import { atomicPrivateWrite, hashFile, readPrivate } from '../storage/files.js';
import { profilePatch } from './profile.js';
import { BridgeClient, EngineError } from './transport.js';

export type EngineOptions = { home: string; workspace: string; plugin: string; binary: string;
  binarySha256: string; apiKey: string; baseUrl: string; model: string };
export interface Engine {
  readonly connected: boolean;
  start(): Promise<void>;
  call(method: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<unknown>;
  events(onConnected?: () => void): AsyncIterable<BridgeEvent>;
  close(): Promise<void>;
}
export class DshRuntime implements Engine {
  private harness?: DeepSeekHarness;
  private bridge?: BridgeClient;
  private launch?: string;
  private starting?: Promise<void>;
  private closing?: Promise<void>;
  private readonly lifetime = new AbortController();
  processId?: number;
  constructor(private readonly options: EngineOptions) {}
  get connected(): boolean { return this.bridge?.connected ?? false; }
  start(): Promise<void> {
    if (this.closing) return Promise.reject(new EngineError('引擎已关闭'));
    this.starting ??= this.launchRuntime(); return this.starting;
  }
  private async launchRuntime(): Promise<void> {
    const options = this.options;
    try {
      if (process.platform !== 'darwin' || process.arch !== 'arm64') throw new EngineError('此平台的 DSH 原生运行时尚未验收');
      if (![options.apiKey, options.baseUrl, options.model].every(value => value.trim())) throw new EngineError('请先配置模型服务');
      const base = new URL(options.baseUrl);
      if (!['http:', 'https:'].includes(base.protocol) || base.username || base.password || base.hash) throw new EngineError('模型服务地址无效');
      for (const path of [options.home, options.workspace, options.plugin, options.binary]) {
        if (!isAbsolute(path)) throw new EngineError('引擎路径必须为绝对路径');
      }
      if (!/^[a-f0-9]{64}$/.test(options.binarySha256) || await hashFile(options.binary) !== options.binarySha256) {
        throw new EngineError('DSH 原生文件校验失败');
      }
      if (!(await lstat(options.plugin)).isFile()) throw new EngineError('DSH 插件文件不可用');
      await mkdir(options.home, { recursive: true, mode: 0o700 });
      if ((await lstat(options.home)).isSymbolicLink()) throw new EngineError('引擎目录不可为符号链接');
      await chmod(options.home, 0o700);
      this.launch = await mkdtemp(join(options.home, 'bridge-'));
      const token = randomBytes(48).toString('base64url');
      const patch = join(this.launch, 'plugin.patch.json'), readyPath = join(this.launch, 'ready.json');
      const pidPath = join(this.launch, 'owner.pid');
      await atomicPrivateWrite(patch, Buffer.from(JSON.stringify(profilePatch(options.plugin))));
      this.lifetime.signal.throwIfAborted();
      this.harness = new DeepSeekHarness({
        dshBin: fileURLToPath(new URL('./native-entry.cjs', import.meta.url)), dshHome: resolve(options.home),
        processCwd: options.workspace, cwd: options.workspace, profile: 'sdk', patches: [patch],
        provider: 'deepseek-official', model: options.model, initializeTimeoutMs: 30_000, requestTimeoutMs: 15_000,
        env: { PATH: '/usr/bin:/bin', HOME: options.home, TMPDIR: this.launch, LANG: 'en_US.UTF-8',
          ELECTRON_RUN_AS_NODE: '1', LOBUDDY_DSH_BINARY: options.binary, LOBUDDY_DSH_PID_FILE: pidPath,
          LOBUDDY_BRIDGE_TOKEN: token, LOBUDDY_BRIDGE_READY: readyPath,
          LOBUDDY_DSH_PROVIDER: 'deepseek-official', LOBUDDY_DSH_MODEL: options.model,
          LOBUDDY_IMAGE_ROOT: join(options.home, '..', 'images'), DEEPSEEK_API_KEY: options.apiKey,
          DEEPSEEK_BASE_URL: options.baseUrl, DSH_TELEMETRY_DISABLED: '1' },
      });
      await this.harness.start();
      const deadline = Date.now() + 15_000;
      for (;;) {
        this.lifetime.signal.throwIfAborted();
        try {
          const info = await lstat(readyPath);
          if (!info.isFile() || (info.mode & 0o777) !== 0o600) throw new EngineError('引擎就绪文件权限无效');
          const ready = BridgeReadySchema.parse(JSON.parse((await readPrivate(readyPath, 4096)).toString()));
          if (Number((await readPrivate(pidPath, 128)).toString()) !== ready.pid) throw new EngineError('引擎进程身份不匹配');
          this.processId = ready.pid; this.bridge = new BridgeClient(ready.port, token); break;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
          if (Date.now() >= deadline) throw new EngineError('引擎未在时限内就绪');
          await delay(50, undefined, { signal: this.lifetime.signal });
        }
      }
      await this.call('health', {});
    } catch (error) {
      await this.dispose();
      throw error instanceof EngineError ? error : new EngineError('引擎启动失败，未自动重试');
    }
  }
  call(method: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
    if (!this.bridge || this.closing) return Promise.reject(new EngineError('引擎未连接'));
    return this.bridge.call(method, params, signal);
  }
  async *events(onConnected?: () => void): AsyncGenerator<BridgeEvent> {
    if (!this.bridge || this.closing) throw new EngineError('引擎未连接');
    yield* this.bridge.events(onConnected);
  }
  close(): Promise<void> {
    this.closing ??= (async () => {
      this.lifetime.abort(); this.bridge?.close();
      await this.starting?.catch(() => {});
      await this.dispose();
    })(); return this.closing;
  }
  private async dispose(): Promise<void> {
    this.bridge?.close(); this.bridge = undefined;
    // Retain ownership and private startup evidence if SDK cannot confirm exit.
    try { await this.harness?.close(); }
    catch { throw new EngineError('无法确认引擎已退出；保留恢复信息，禁止自动重启'); }
    this.harness = undefined; this.processId = undefined;
    if (this.launch) await rm(this.launch, { recursive: true, force: true });
    this.launch = undefined;
  }
}
