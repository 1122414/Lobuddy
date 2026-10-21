import { EventEmitter } from 'node:events';
import { randomUUID } from 'node:crypto';
import { assertFrameSize, ServerFrameSchema, PROTOCOL_VERSION, RequestSchema,
  requestSchemas, responseSchemas, TRANSIENT_METHOD_NAMES, type Method, type ParametersByMethod,
  type ResultsByMethod } from '@lobuddy/contracts';
import { EventCursor } from '@lobuddy/domain';
import type { MessageTransport } from './transport.js';
import { RpcFault } from './fault.js';

type Pending = { method: Method; resolve: (value: unknown) => void; reject: (error: RpcFault) => void; timer: NodeJS.Timeout };
export class RpcClient extends EventEmitter {
  private instance?: string;
  private cursor?: EventCursor;
  private closed = false;
  private started = false;
  private readonly pending = new Map<string, Pending>();
  private readonly requests = new Map<string, { fingerprint: string; result: Promise<unknown> }>();
  private readonly detach: (() => void)[];
  private resolveReady?: () => void;
  private rejectReady?: (error: RpcFault) => void;
  readonly ready: Promise<void>;
  methods: readonly Method[] = [];
  get instanceId(): string | undefined { return this.instance; }
  constructor(private readonly transport: MessageTransport, private readonly timeoutMs = 20_000) {
    super();
    this.ready = new Promise((resolve, reject) => { this.resolveReady = resolve; this.rejectReady = reject; });
    void this.ready.catch(() => {});
    this.detach = [transport.onMessage(value => this.receive(value)), transport.onClose(() => this.fail())];
  }
  start(): Promise<void> {
    if (this.started || this.closed) return Promise.reject(new RpcFault('unavailable'));
    this.started = true;
    const timer = setTimeout(() => this.fail(), this.timeoutMs);
    void this.ready.finally(() => clearTimeout(timer)).catch(() => {});
    try { this.transport.send({ kind: 'hello', protocol: PROTOCOL_VERSION, client_id: randomUUID() }); }
    catch { this.fail(); }
    return this.ready;
  }
  request<M extends Method>(method: M, params: ParametersByMethod[M], id: string = randomUUID()): Promise<ResultsByMethod[M]> {
    const reject = (code: RpcFault['code']) => Promise.reject(new RpcFault(code));
    if (!this.instance || this.closed) return reject('unavailable');
    if (!Object.hasOwn(requestSchemas, method)) return reject('invalid_request');
    const parsed = requestSchemas[method]?.safeParse(params);
    if (!parsed?.success) return reject('invalid_request');
    let frame: ReturnType<typeof RequestSchema.parse>;
    try {
      // Retain caller field order/default omission for transport request identity.
      frame = RequestSchema.parse({ kind: 'request', protocol: PROTOCOL_VERSION, instance_id: this.instance,
        jsonrpc: '2.0', id, method, params });
      assertFrameSize(frame);
    } catch { return reject('invalid_request'); }
    const fingerprint = JSON.stringify({ method, params });
    const existing = this.requests.get(id);
    if (existing) return (existing.fingerprint === fingerprint ? existing.result : reject('id_conflict')) as Promise<ResultsByMethod[M]>;
    if (this.requests.size >= 8192 || this.pending.size >= 64) return reject('unavailable');
    const result = new Promise<unknown>((resolve, rejectRequest) => {
      const timer = setTimeout(() => { this.pending.delete(id); rejectRequest(new RpcFault('timeout')); }, this.timeoutMs);
      this.pending.set(id, { method, resolve, reject: rejectRequest, timer });
    });
    this.requests.set(id, { fingerprint, result });
    if (TRANSIENT_METHOD_NAMES.includes(method)) void result.finally(() => this.requests.delete(id)).catch(() => {});
    try { this.transport.send(frame); } catch { this.fail(); }
    return result as Promise<ResultsByMethod[M]>;
  }
  private receive(value: unknown): void {
    if (this.closed) return;
    try {
      assertFrameSize(value); const frame = ServerFrameSchema.parse(value);
      if (frame.kind === 'ready') {
        if (!this.started || this.instance) throw new RpcFault('invalid_request');
        this.instance = frame.instance_id; this.cursor = new EventCursor(frame.instance_id, frame.sequence);
        this.methods = frame.methods;
        this.emit('resync', 'new-instance'); this.resolveReady?.(); this.emit('connected', true); return;
      }
      if (!this.instance || frame.instance_id !== this.instance) return;
      if (frame.kind === 'closed') { this.fail(); return; }
      if (frame.kind === 'event') {
        const action = this.cursor!.accept(frame.instance_id, frame.event.sequence);
        if (action === 'apply') this.emit('event', frame.event);
        if (action === 'resync') { this.emit('resync', 'event-gap'); this.fail(); }
        return;
      }
      const pending = this.pending.get(frame.id);
      if (!pending) return;
      if (!frame.outcome.ok) {
        clearTimeout(pending.timer); this.pending.delete(frame.id); pending.reject(new RpcFault(frame.outcome.code));
      } else {
        const result = responseSchemas[pending.method].parse(frame.outcome.result);
        clearTimeout(pending.timer); this.pending.delete(frame.id); pending.resolve(result);
      }
    } catch { this.fail(); }
  }
  private fail(): void {
    if (this.closed) return;
    this.closed = true; this.rejectReady?.(new RpcFault('unavailable'));
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(new RpcFault('unavailable')); }
    this.pending.clear(); for (const detach of this.detach) detach();
    this.transport.close(); this.emit('connected', false);
  }
  close(): void {
    try { if (!this.closed && this.instance) this.transport.send({ kind: 'close', instance_id: this.instance }); }
    finally { this.fail(); }
  }
}
