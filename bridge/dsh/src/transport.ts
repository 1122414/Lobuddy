import { timingSafeEqual } from 'node:crypto';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { writeFile, unlink } from 'node:fs/promises';

export type ObjectValue = Record<string, unknown>;
export type Dispatch = (method: string, params: ObjectValue) => Promise<unknown>;
export const object = (value: unknown): ObjectValue => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw Error('Expected object');
  return value as ObjectValue;
};
export const text = (value: unknown, max = 128): string => {
  if (typeof value !== 'string' || !value.length || value.length > max) throw Error('Invalid string');
  return value;
};

/** Single authenticated owner; losing its event stream invalidates outstanding work. */
export class BridgeTransport {
  private stream?: ServerResponse;
  private requests = new Map<string, { body: string; result: Promise<unknown> }>();
  private server = createServer((req, res) => { void this.handle(req, res); });
  private heartbeat?: ReturnType<typeof setInterval>;
  private port = 0;
  constructor(
    private token: string,
    private readyPath: string,
    private dispatch: Dispatch,
    private disconnected: () => void,
  ) {
    if (token.length < 32) throw Error('Missing bridge credential');
  }
  get connected(): boolean { return !!this.stream && !this.stream.destroyed; }
  async start(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.server.once('error', reject);
      this.server.listen(0, '127.0.0.1', () => resolve());
    });
    const address = this.server.address();
    if (!address || typeof address === 'string') throw Error('Invalid address');
    this.port = address.port;
    try {
      await writeFile(this.readyPath, JSON.stringify({ port: this.port, pid: process.pid, protocol: 1 }),
        { mode: 0o600, flag: 'wx' });
    } catch (error) {
      this.server.close();
      throw error;
    }
    this.heartbeat = setInterval(() => {
      if (this.connected) this.stream!.write(': heartbeat\n\n');
    }, 5000);
    this.heartbeat.unref();
  }
  emit(event: ObjectValue): void {
    if (!this.connected) throw Error('Bridge event stream disconnected');
    this.stream!.write(`data: ${JSON.stringify(event)}\n\n`);
    if (this.stream!.writableLength > 1024 * 1024) {
      // A stalled owner cannot keep running tools or accumulate unbounded output.
      this.stream!.destroy();
      this.disconnected();
    }
  }
  async close(): Promise<void> {
    clearInterval(this.heartbeat);
    this.disconnected();
    this.stream?.destroy();
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
    await unlink(this.readyPath).catch(() => undefined);
  }
  private authorized(req: IncomingMessage): boolean {
    const received = Buffer.from(req.headers.authorization ?? '');
    const expected = Buffer.from(`Bearer ${this.token}`);
    return !req.headers.origin && req.headers.host === `127.0.0.1:${this.port}` &&
      received.length === expected.length && timingSafeEqual(received, expected);
  }
  private async handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    if (!this.authorized(req)) { res.writeHead(403).end(); return; }
    if (req.method === 'GET' && req.url === '/events') {
      if (this.connected) { res.writeHead(409).end(); return; }
      this.stream = res;
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' });
      res.write(': connected\n\n');
      res.once('close', () => {
        if (this.stream === res) { this.stream = undefined; this.disconnected(); }
      });
      return;
    }
    if (req.method !== 'POST' || req.url !== '/rpc') { res.writeHead(404).end(); return; }
    let id: unknown = null;
    try {
      const chunks: Buffer[] = [];
      let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 1024 * 1024) throw Error('Request too large');
        chunks.push(chunk);
      }
      const body = Buffer.concat(chunks).toString('utf8');
      const rpc = object(JSON.parse(body));
      if (rpc.jsonrpc !== '2.0') throw Error('Invalid protocol');
      id = text(rpc.id);
      const method = text(rpc.method);
      const params = object(rpc.params);
      const key = id as string;
      let entry = this.requests.get(key);
      if (entry && entry.body !== body) throw Error('Request ID conflict');
      if (!entry) {
        if (this.requests.size >= 8192) throw Error('Request limit reached; restart when idle');
        entry = { body, result: Promise.resolve().then(() => this.dispatch(method, params)) };
        this.requests.set(key, entry);
      }
      const result = await entry.result;
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id, result }));
    } catch {
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({
        jsonrpc: '2.0', id, error: { code: -32602, message: 'Request rejected or execution unavailable' },
      }));
    }
  }
}
