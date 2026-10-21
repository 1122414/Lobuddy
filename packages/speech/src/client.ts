import { randomUUID } from 'node:crypto';
import { SpeechReplySchema,type SpeechDriver,type SpeechEvent,type SpeechCommand } from './protocol.js';
export interface SpeechTransport {
  send(value: unknown): void; close(): void;
  onMessage(listener: (value: unknown) => void): () => void;
  onClose(listener: () => void): () => void;
}
export class SpeechClient implements SpeechDriver {
  event = (_event: SpeechEvent) => {};
  fault = () => {};
  private closed = false;
  private readonly pending = new Map<string,{ resolve: (ready: boolean) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  constructor(private readonly transport: SpeechTransport) {
    transport.onMessage(raw => {
      const parsed = SpeechReplySchema.safeParse(raw); if (!parsed.success) { this.fail(); return; }
      const packet = parsed.data;
      if (packet.kind === 'booted') return;
      if (packet.kind === 'fault') { this.fail(); return; }
      if (packet.kind === 'event') { this.event(packet.event); return; }
      const pending = this.pending.get(packet.id); if (!pending) return;
      this.pending.delete(packet.id); clearTimeout(pending.timer);
      if (packet.ok) pending.resolve(packet.ready); else pending.reject(Error('本地语音操作未完成'));
    });
    transport.onClose(() => { this.closed = true; this.fail(); });
  }
  request(command: SpeechCommand): Promise<boolean> {
    if (this.closed || this.pending.size >= 40) return Promise.reject(Error('本地语音进程不可用'));
    const id = randomUUID();
    return new Promise((resolve,reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(Error('本地语音操作超时')); this.fail(); },command.kind === 'download' ? 1800000 : command.kind === 'start' ? 60000 : 10000);
      this.pending.set(id,{ resolve,reject,timer });
      try { this.transport.send({ id,command }); } catch { this.fail(); }
    });
  }
  private fail(): void {
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.reject(Error('本地语音进程已断开')); } this.pending.clear(); this.fault();
  }
  async close(): Promise<void> { this.closed = true; this.transport.close(); this.fail(); }
}
