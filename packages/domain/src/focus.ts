import { randomUUID } from 'node:crypto';
export type FocusState = 'idle' | 'focusing' | 'paused' | 'break' | 'completed' | 'stopped';
export type FocusSession = { id: string; minutes: number; breakMinutes: number; state: FocusState; endsAt: number; pausedRemaining: number };
export class FocusTimer {
  session: FocusSession | undefined;
  completedCount = 0;
  constructor(private readonly settings: () => { focus_default_minutes: number; focus_break_minutes: number; focus_auto_loop: boolean },
    private readonly completed: (session: Readonly<FocusSession>) => void, private readonly clock = Date.now) {}
  get active(): boolean { return Boolean(this.session && ['focusing','paused','break'].includes(this.session.state)); }
  get remaining(): number {
    if (!this.session) return 0;
    return this.session.state === 'paused' ? this.session.pausedRemaining : Math.max(0, Math.trunc((this.session.endsAt - this.clock()) / 1000));
  }
  start(minutes?: number | null): void {
    const settings = this.settings(), duration = minutes || settings.focus_default_minutes;
    this.session = { id: randomUUID(), minutes: duration, breakMinutes: settings.focus_break_minutes,
      state: 'focusing', endsAt: this.clock() + duration * 60000, pausedRemaining: 0 };
  }
  pause(): void {
    if (this.session?.state !== 'focusing') return;
    this.session.pausedRemaining = this.remaining; this.session.state = 'paused';
  }
  resume(): void {
    if (this.session?.state !== 'paused') return;
    this.session.endsAt = this.clock() + this.session.pausedRemaining * 1000; this.session.state = 'focusing';
  }
  stop(): void { this.session = undefined; }
  poll(): void {
    const session = this.session;
    if (!session || !['focusing','break'].includes(session.state) || this.remaining > 0) return;
    if (session.state === 'break') { session.state = 'idle'; return; }
    session.state = 'completed'; this.completedCount++;
    if (this.settings().focus_auto_loop) { session.state = 'break'; session.endsAt = this.clock() + session.breakMinutes * 60000; }
    else this.session = undefined;
    this.completed({ ...session });
  }
  view() { return { state: this.session?.state ?? 'idle', seconds_remaining: this.remaining, completed_count: this.completedCount }; }
}
