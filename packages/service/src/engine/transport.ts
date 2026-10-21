import { request, type IncomingMessage } from 'node:http';
import { randomUUID } from 'node:crypto';
import { BridgeEventSchema, BridgeResponseSchema, type BridgeEvent } from '@lobuddy/contracts';

export class EngineError extends Error {}
const MAX_FRAME = 1024 * 1024;
export class BridgeClient {
  private readonly lifetime = new AbortController();
  private streaming = false;
  private sequence = 0;
  connected = false;
  constructor(private readonly port: number, private readonly token: string) {
    if (!Number.isInteger(port) || port < 1 || port > 65535 || token.length < 32) throw new EngineError('引擎连接信息无效');
  }
  private response(path: string, body: string | undefined, signal: AbortSignal): Promise<IncomingMessage> {
    return new Promise((resolve, reject) => {
      const req = request({ hostname: '127.0.0.1', port: this.port, path, method: body === undefined ? 'GET' : 'POST',
        signal, agent: false, headers: { Authorization: `Bearer ${this.token}`, ...(body === undefined ? {} : {
          'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body),
        }) } }, res => {
        if (res.statusCode !== 200) { res.destroy(); reject(new EngineError('引擎连接被拒绝')); return; }
        resolve(res);
      });
      req.once('error', () => reject(new EngineError('引擎连接中断，未自动重试')));
      req.end(body);
    });
  }
  async call(method: string, params: Record<string, unknown>, signal?: AbortSignal): Promise<unknown> {
    const id = randomUUID(), body = JSON.stringify({ jsonrpc: '2.0', id, method, params });
    if (Buffer.byteLength(body) > MAX_FRAME) throw new EngineError('引擎请求超过限制');
    const timeout = AbortSignal.timeout(method === 'analysis.run' ? 50_000 : 15_000);
    const combined = AbortSignal.any([timeout, this.lifetime.signal, ...(signal ? [signal] : [])]);
    const response = await this.response('/rpc', body, combined);
    try {
      const chunks: Buffer[] = []; let size = 0;
      for await (const block of response) {
        size += block.length;
        if (size > MAX_FRAME) throw new EngineError('引擎返回超过限制');
        chunks.push(block);
      }
      const parsed = BridgeResponseSchema.safeParse(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      if (!parsed.success || parsed.data.id !== id) throw new EngineError('引擎返回协议不匹配');
      if (parsed.data.error) {
        const kind = parsed.data.error.data?.kind;
        const safe = ['busy', 'analysis_unavailable', 'analysis_incomplete', 'analysis_truncated', 'analysis_output_exceeded'].includes(kind ?? '') ? kind : 'request_rejected';
        const operation = ['health','session.open','turn.send','turn.cancel','tool.resolve','analysis.run','context.update'].includes(method) ? method : 'request';
        throw new EngineError(`引擎拒绝 ${operation} 请求（${safe}），未自动重试`);
      }
      return parsed.data.result;
    } catch (error) {
      throw error instanceof EngineError ? error : new EngineError('引擎返回无效或连接中断');
    } finally { response.destroy(); }
  }
  async *events(onConnected: () => void = () => {}): AsyncGenerator<BridgeEvent> {
    if (this.streaming || this.lifetime.signal.aborted) throw new EngineError('事件流不可用');
    this.streaming = true;
    let response: IncomingMessage | undefined;
    try {
      response = await this.response('/events', undefined, this.lifetime.signal);
      if (!response.headers['content-type']?.startsWith('text/event-stream')) throw new EngineError('事件流类型无效');
      response.setTimeout(15_000, () => response?.destroy(new EngineError('事件流超时')));
      this.connected = true; onConnected();
      let pending = Buffer.alloc(0);
      for await (const block of response) {
        pending = Buffer.concat([pending, block]);
        let end: number;
        while ((end = pending.indexOf(10)) !== -1) {
          if (end > MAX_FRAME) throw new EngineError('引擎事件超过限制');
          const line = pending.subarray(0, end).toString('utf8'); pending = pending.subarray(end + 1);
          if (!line.startsWith('data: ')) continue;
          const parsed = BridgeEventSchema.safeParse(JSON.parse(line.slice(6)));
          if (!parsed.success) throw new EngineError('引擎事件格式无效');
          if (parsed.data.sequence !== this.sequence + 1) throw new EngineError('引擎事件丢失或乱序，需要恢复');
          this.sequence = parsed.data.sequence; yield parsed.data;
        }
        if (pending.length > MAX_FRAME) throw new EngineError('引擎事件超过限制');
      }
      throw new EngineError('引擎事件流已断开，未自动重试');
    } catch (error) {
      if (this.lifetime.signal.aborted) return;
      throw error instanceof EngineError ? error : new EngineError('引擎事件流已断开或无效');
    } finally { this.connected = false; this.streaming = false; response?.destroy(); }
  }
  close(): void { this.connected = false; this.lifetime.abort(); }
}
