import { randomUUID } from 'node:crypto';
import { assertFrameSize, ClientFrameSchema, PROTOCOL_VERSION, requestSchemas, responseSchemas,
  TRANSIENT_METHOD_NAMES, type Method, type NormalizedParametersByMethod, type ResultsByMethod,
  type Request, type ServerFrame, type ServiceEvent, ServiceEventSchema } from '@lobuddy/contracts';
import type { MessageTransport } from './transport.js';
import { RpcFault } from './fault.js';

type Context = { requestId: string; signal: AbortSignal };
export type Handler<M extends Method> = (params: NormalizedParametersByMethod[M], context: Context) => Promise<ResultsByMethod[M]> | ResultsByMethod[M];
export type Handlers = { [M in Method]?: Handler<M> };
type Response = Extract<ServerFrame, { kind: 'response' }>;
export class RpcServer {
  readonly instanceId = randomUUID();
  private ready = false;
  private closed = false;
  private closing?: Promise<void>;
  private sequence = 0;
  private active = 0;
  private readonly lifetime = new AbortController();
  private readonly requests = new Map<string, { fingerprint: string; response: Promise<Response> }>();
  private readonly detach: (() => void)[];

  constructor(private readonly transport: MessageTransport, private readonly handlers: Handlers,
    private readonly shutdown: () => Promise<void> = async () => {}) {
    this.detach = [transport.onMessage(value => { void this.receive(value).catch(() => {}); }),
      transport.onClose(() => { void this.close().catch(() => {}); })];
  }
  private send(value: ServerFrame): void {
    if (this.closed) return;
    assertFrameSize(value); this.transport.send(value);
  }
  private async receive(value: unknown): Promise<void> {
    if (this.closed || this.closing) return;
    try {
      assertFrameSize(value);
      const frame = ClientFrameSchema.parse(value);
      if (frame.kind === 'hello') {
        if (this.ready) throw new RpcFault('invalid_request');
        this.ready = true;
        this.send({ kind: 'ready', protocol: PROTOCOL_VERSION, instance_id: this.instanceId,
          capabilities: ['runtime-validation', 'events', 'bounded-requests'],
          methods: Object.keys(this.handlers) as Method[], sequence: this.sequence });
        return;
      }
      if (!this.ready || frame.instance_id !== this.instanceId) throw new RpcFault('not_ready');
      if (frame.kind === 'close') { await this.close(); return; }
      const fingerprint = JSON.stringify({ method: frame.method, params: frame.params });
      const existing = this.requests.get(frame.id);
      if (existing) {
        this.send(existing.fingerprint === fingerprint ? await existing.response : this.failure(frame.id, 'id_conflict'));
        return;
      }
      if (this.requests.size >= 8192 || this.active >= 64) {
        this.send(this.failure(frame.id, 'unavailable')); return;
      }
      this.active++;
      const response = this.dispatch(frame).finally(() => { this.active--; });
      this.requests.set(frame.id, { fingerprint, response });
      try { this.send(await response); }
      finally { if (TRANSIENT_METHOD_NAMES.includes(frame.method)) this.requests.delete(frame.id); }
    } catch { await this.close(); }
  }
  private failure(id: string, code: RpcFault['code']): Response {
    return { kind: 'response', instance_id: this.instanceId, jsonrpc: '2.0', id, outcome: { ok: false, code } };
  }
  private async dispatch<M extends Method>(request: Request & { method: M }): Promise<Response> {
    const parsed = requestSchemas[request.method].safeParse(request.params);
    if (!parsed.success) return this.failure(request.id, 'invalid_request');
    const handler = this.handlers[request.method] as Handler<M> | undefined;
    if (!handler) return this.failure(request.id, 'unsupported_method');
    try {
      const raw = await handler(parsed.data as NormalizedParametersByMethod[M], { requestId: request.id, signal: this.lifetime.signal });
      const result = responseSchemas[request.method].parse(raw);
      return { kind: 'response', instance_id: this.instanceId, jsonrpc: '2.0', id: request.id,
        outcome: { ok: true, result } };
    } catch (error) { return this.failure(request.id, error instanceof RpcFault ? error.code : 'internal_error'); }
  }
  publish(event: Omit<ServiceEvent, 'sequence'>): void {
    if (!this.ready || this.closing || this.closed) return;
    const next = ServiceEventSchema.parse({ ...event, sequence: this.sequence + 1 });
    this.send({ kind: 'event', instance_id: this.instanceId, event: next });
    this.sequence = next.sequence;
  }
  close(): Promise<void> {
    this.closing ??= this.finish();
    return this.closing;
  }
  private async finish(): Promise<void> {
    this.lifetime.abort();
    try { await this.shutdown(); }
    finally {
      try { this.send({ kind: 'closed', instance_id: this.instanceId }); }
      finally {
        this.closed = true; for (const detach of this.detach) detach(); this.transport.close();
      }
    }
  }
}
