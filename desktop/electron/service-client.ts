import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { METHOD_NAMES, type ParametersByMethod, type ServiceEvent } from '../../shared/desktop-protocol';
import type { ResultsByMethod } from '../../shared/desktop-api';
import { fingerprint } from './policy';

interface Pending { resolve: (value: unknown) => void; reject: (reason: Error) => void; timer: NodeJS.Timeout }
export class ServiceClient extends EventEmitter {
  private child?: ChildProcessWithoutNullStreams;
  private pending = new Map<string, Pending>();
  private requests = new Map<string, { fingerprint: string; result: Promise<unknown> }>();
  private sequence = 0;
  private buffer = '';
  private closing = false;
  private stopping?: Promise<void>;
  connected = false;
  start(python: string, root: string, data: string, workspace: string): void {
    if (this.child) throw new Error('Service already started');
    const child = spawn(python, ['-m', 'app.service', '--data-dir', data, '--workspace', workspace], {
      cwd: root, stdio: ['pipe', 'pipe', 'pipe'], detached: process.platform !== 'win32',
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
    });
    this.child = child;
    child.stdout.setEncoding('utf8');
    child.stdout.on('data', (chunk: string) => {
      this.buffer += chunk;
      if (Buffer.byteLength(this.buffer) > 1024 * 1024) { this.fail(); void this.stop(); return; }
      let newline: number;
      while ((newline = this.buffer.indexOf('\n')) >= 0) {
        const line = this.buffer.slice(0, newline); this.buffer = this.buffer.slice(newline + 1);
        try { this.receive(JSON.parse(line)); } catch { this.fail(); void this.stop(); return; }
      }
    });
    // Consume diagnostics without forwarding provider details or credentials to the renderer.
    child.stderr.setEncoding('utf8');
    child.stderr.on('data', (chunk: string) => {
      const type = /Task executor failed: ([A-Za-z]+)/.exec(chunk)?.[1];
      if (type) this.emit('diagnostic', type);
    });
    child.stdin.on('error', () => this.fail());
    child.on('error', () => this.fail());
    child.on('exit', () => {
      this.fail();
      // If Python crashes, terminate only its owned process group, including the DSH child.
      if (process.platform !== 'win32' && child.pid) {
        try { process.kill(-child.pid, 'SIGKILL'); } catch { /* Group already exited. */ }
      }
    });
  }
  private receive(message: Record<string, unknown>): void {
    if (message.jsonrpc !== '2.0') throw new Error('Invalid service protocol');
    if (message.method === 'event') {
      const event = message.params as ServiceEvent;
      if (!event || !Number.isSafeInteger(event.sequence) || event.sequence <= this.sequence ||
          !['session_id', 'task_id', 'turn_id', 'kind'].every(key => typeof (event as unknown as Record<string, unknown>)[key] === 'string')) throw new Error('Invalid event');
      if (this.sequence && event.sequence !== this.sequence + 1) throw new Error('Event gap');
      this.sequence = event.sequence;
      this.emit('event', event);
      return;
    }
    const id = message.id;
    if (typeof id !== 'string') throw new Error('Invalid response');
    const pending = this.pending.get(id);
    if (!pending) return;
    clearTimeout(pending.timer); this.pending.delete(id);
    if (message.error) pending.reject(new Error('操作未完成，请检查配置或服务状态。'));
    else pending.resolve(message.result);
  }
  request<M extends keyof ParametersByMethod>(method: M, params: unknown, id: string): Promise<ResultsByMethod[M]>;
  request(method: keyof ParametersByMethod, params: unknown, id: string): Promise<unknown> {
    if (!METHOD_NAMES.includes(method) || typeof id !== 'string' || !id.length || id.length > 128 || !params || typeof params !== 'object' || Array.isArray(params)) return Promise.reject(new Error('Invalid business request'));
    const signature = fingerprint(method, params);
    if (Buffer.byteLength(signature) > 1024 * 1024) return Promise.reject(new Error('Request too large'));
    const existing = this.requests.get(id);
    if (existing) return existing.fingerprint === signature ? existing.result : Promise.reject(new Error('Request ID conflict'));
    if (!this.child || this.closing || this.child.exitCode !== null || this.requests.size >= 8192 || this.pending.size >= 64) return Promise.reject(new Error('业务服务不可用，请重新启动应用。'));
    const result = new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('请求超时，未自动重试。请查看任务状态。')); }, method === 'credential.configure' ? 130_000 : 20_000);
      this.pending.set(id, { resolve, reject, timer });
      this.child!.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n', error => {
        if (error) this.fail();
      });
    });
    this.requests.set(id, { fingerprint: signature, result });
    if (["theme.list", "theme.from_image", "companion.get", "image.get", "service.health", "session.list", "session.history", "task.list", "task.get", "approval.list", "pet.get", "progress.get", "settings.get", "focus.get", "memory.list", "history.search", "history.summaries", "skill.list", "skill.get", "skill.candidates"].includes(method)) {
      void result.finally(() => this.requests.delete(id)).catch(() => undefined);
    }
    return result;
  }
  async handshake(): Promise<void> {
    const health = await this.request('service.health', {}, 'startup-health') as { protocol: number };
    if (health.protocol !== 1) throw new Error('Unsupported protocol');
    this.connected = true; this.emit('status', true);
  }
  private fail(): void {
    this.connected = false; this.emit('status', false);
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new Error('业务服务已断开，任务不会自动重试。')); }
    this.pending.clear();
  }
  async denyApprovals(): Promise<void> {
    if (!this.connected || this.closing) return;
    try {
      const approvals = await this.request('approval.list', {}, crypto.randomUUID()) as Array<{ approval_id: string }>;
      await Promise.all(approvals.map(item => this.request('approval.resolve', { approval_id: item.approval_id, approved: false }, crypto.randomUUID()).catch(() => undefined)));
    } catch { /* A dead service cannot approve any action. */ }
  }
  stop(): Promise<void> {
    this.stopping ??= this.shutdown();
    return this.stopping;
  }
  private async shutdown(): Promise<void> {
    this.closing = true;
    const child = this.child;
    if (child && child.exitCode === null && child.pid) {
      child.stdin.end();
      await new Promise<void>(resolve => {
        const timer = setTimeout(() => {
          try { process.platform === 'win32' ? child.kill('SIGKILL') : process.kill(-child.pid!, 'SIGKILL'); } catch { /* Already exited. */ }
          resolve();
        }, 50_000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
      });
    }
    this.fail();
  }
}
