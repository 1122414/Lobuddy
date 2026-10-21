import { randomUUID } from 'node:crypto';
import type { TurnState, ResultsByMethod } from '@lobuddy/contracts';
type Approval = ResultsByMethod['approval.list'][number];
type Pending = { view: Approval; finish: (allowed: boolean) => void; active: () => boolean };
export class Approvals {
  private readonly pending = new Map<string, Pending>();
  constructor(private readonly emit: (state: TurnState, kind: string, data: Record<string, string>) => void) {}
  request(state: TurnState, tool: string, command: string, reason: string, timeout: number, signal: AbortSignal, active: () => boolean): Promise<boolean> {
    if (signal.aborted || !active()) return Promise.resolve(false);
    const id = randomUUID();
    return new Promise<boolean>(resolve => {
      const abort = () => finish(false);
      const timer = setTimeout(abort, timeout);
      const finish = (allowed: boolean) => {
        clearTimeout(timer); signal.removeEventListener('abort', abort); this.pending.delete(id);
        resolve(allowed && !signal.aborted && active());
      };
      this.pending.set(id, { view: { approval_id: id, turn_id: state.turn_id, session_id: state.session_id, command, reason }, finish, active });
      signal.addEventListener('abort', abort, { once: true });
      try { this.emit(state, 'approval.requested', { approval_id: id, command, reason, tool_name: tool }); }
      catch { finish(false); }
    });
  }
  list(): Approval[] { return [...this.pending.values()].map(item => ({ ...item.view })); }
  resolve(id: string, allowed: boolean): boolean {
    const item = this.pending.get(id); if (!item || !item.active()) return false;
    item.finish(allowed); return true;
  }
  deny(turnId?: string): void {
    for (const item of this.pending.values()) if (!turnId || item.view.turn_id === turnId) item.finish(false);
  }
}
