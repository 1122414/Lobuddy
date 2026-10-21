/** A cursor never infers missing effects or manufactures events after a gap. */
export * from './growth.js';
export * from './execution-intent.js';
export * from './focus.js';
export * from './memory.js';
export * from './colors.js';
export class EventCursor {
  private valid = true;
  constructor(readonly instanceId: string, private sequence = 0) {}
  accept(instanceId: string, sequence: number): 'apply' | 'stale' | 'resync' {
    if (instanceId !== this.instanceId || sequence <= this.sequence) return 'stale';
    if (!this.valid || sequence !== this.sequence + 1) { this.valid = false; return 'resync'; }
    this.sequence = sequence;
    return 'apply';
  }
}
