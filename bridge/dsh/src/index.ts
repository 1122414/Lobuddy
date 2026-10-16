import type { Context } from '@deepseek-ai/cordis';
import type { AgentHandle } from '@deepseek-ai/dsh-agent';
import type { ToolRunContext } from '@deepseek-ai/dsh-tools';
import type { SessionId } from '@deepseek-ai/dsh-session';
import type { MessageId } from '@deepseek-ai/dsh-llm';
import { randomUUID } from 'node:crypto';
import { BridgeTransport, object, text, type ObjectValue } from './transport.js';

export const name = 'lobuddy-bridge';
export const inject = ['agents', 'tools'];
const toolNames = ['lobuddy_read_file', 'lobuddy_write_file'];
type Turn = { sessionId: string; taskId: string; turnId: string; lane: string; cancelled: boolean };
type Pending = { turn: Turn; resolve: (value: unknown) => void; reject: (error: Error) => void };

export async function apply(ctx: Context): Promise<void> {
  const handles = new Map<string, AgentHandle>();
  const active = new Map<string, Turn>();
  const pending = new Map<string, Pending>();
  const seenTurns = new Set<string>();
  const opening = new Set<string>();
  let sequence = 0;
  const emit = (turn: Turn, kind: string, data: ObjectValue): void => {
    bridge.emit({ sessionId: turn.sessionId, taskId: turn.taskId, turnId: turn.turnId,
      sequence: ++sequence, kind, data });
  };
  const cancel = (turn: Turn): void => {
    turn.cancelled = true;
    for (const [id, item] of pending) {
      if (item.turn === turn) { pending.delete(id); item.reject(Error('Cancelled')); }
    }
    handles.get(turn.sessionId)?.agent.cancel({ kind: 'user' });
  };
  const bridge = new BridgeTransport(
    text(process.env.LOBUDDY_BRIDGE_TOKEN), text(process.env.LOBUDDY_BRIDGE_READY, 4096),
    async (method, params) => {
      if (method === 'health') return { protocol: 1, sessions: handles.size, connected: bridge.connected, tools: ctx.tools.schemas().map((tool) => tool.name) };
      if (method === 'session.open') {
        const sessionId = text(params.sessionId);
        if (!/^[a-zA-Z0-9_-]{1,128}$/.test(sessionId)) throw Error('Invalid session ID');
        if (handles.has(sessionId)) return { sessionId };
        if (opening.has(sessionId) || handles.size + opening.size >= 32) throw Error('Session busy');
        opening.add(sessionId);
        try {
          const setup = (scope: Context): void => {
            // Resuming a crashed session must never drain its old pending input.
            scope.on('agent/pre-step', async ({ agent }, next) =>
              active.has(agent.id) && bridge.connected ? next() : { kind: 'reject' });
          };
          const agentOptions = { provider: text(process.env.LOBUDDY_DSH_PROVIDER),
            model: text(process.env.LOBUDDY_DSH_MODEL), maxTokens: 2048 };
          const handle = params.resume === true
            ? await ctx.agents.resume({ resumeSessionId: sessionId as SessionId, agentOptions, setup })
            : await ctx.agents.create({ sessionId: sessionId as SessionId, meta: { cwd: process.cwd() }, agentOptions, setup });
          handle.agent.inbox.clear();
          await handle.agent.whenIdle();
          handles.set(sessionId, handle);
          // Durable message ids prevent re-submission of turns after restart.
          for (const event of handle.agent.session.snapshotEvents()) {
            if (event.type === 'user/message') seenTurns.add(event.data.id);
            if (event.type === 'agent/inbox/spliced') {
              for (const message of event.data.inserted) seenTurns.add(message.id);
            }
          }
          return { sessionId };
        } finally { opening.delete(sessionId); }
      }
      if (method === 'turn.send') {
        const turn: Turn = { sessionId: text(params.sessionId), taskId: text(params.taskId),
          turnId: text(params.turnId), lane: text(params.lane), cancelled: false };
        const input = text(params.text, 100000);
        const handle = handles.get(turn.sessionId);
        if (!handle || !bridge.connected || active.has(turn.sessionId) || seenTurns.has(turn.turnId) ||
          !['foreground', 'background'].includes(turn.lane) ||
          [...active.values()].some((item) => item.lane === turn.lane)) throw Error('Turn unavailable');
        active.set(turn.sessionId, turn);
        seenTurns.add(turn.turnId);
        handle.agent.followup({ id: turn.turnId as MessageId, role: 'user', content: [{ type: 'text', text: input }],
          source: { kind: 'user' } });
        emit(turn, 'turn.started', {});
        void handle.agent.whenIdle().then(() => {
          const ending = [...handle.agent.session.snapshotEvents()].reverse().find((e) => e.type === 'turn/end');
          const failed = ending?.type !== 'turn/end' || ending.data.reason.kind !== 'completed';
          if (bridge.connected) emit(turn, turn.cancelled ? 'turn.cancelled' : failed ? 'turn.failed' : 'turn.completed', {});
        }).catch(() => {
          if (bridge.connected) emit(turn, 'turn.failed', {});
        }).finally(() => { if (active.get(turn.sessionId) === turn) active.delete(turn.sessionId); });
        return { turnId: turn.turnId };
      }
      if (method === 'turn.cancel') {
        const turn = active.get(text(params.sessionId));
        if (turn && turn.turnId === text(params.turnId)) cancel(turn);
        return { cancelled: !!turn && turn.turnId === params.turnId };
      }
      if (method === 'tool.resolve') {
        const id = text(params.callId);
        const request = pending.get(id);
        if (!request || request.turn.turnId !== params.turnId) throw Error('Stale tool result');
        pending.delete(id);
        if (params.ok === true) request.resolve(params.value);
        else request.reject(Error(typeof params.error === 'string' ? params.error.slice(0, 500) : 'Tool rejected'));
        return { accepted: true };
      }
      throw Error('Unknown method');
    },
    () => { for (const turn of active.values()) cancel(turn); },
  );
  ctx.tools.guard((exec) => !toolNames.includes(exec.name) || !exec.agent ||
    !handles.has(exec.agent.id) || !active.has(exec.agent.id) || !bridge.connected
    ? 'Tool is not governed by the Lobuddy bridge' : undefined);
  for (const toolName of toolNames) {
    ctx.tools.register({
      name: toolName,
      description: toolName.endsWith('read_file') ? 'Read a UTF-8 file within the allowed workspace.'
        : 'Write a UTF-8 file after explicit user approval. A rejection must be respected.',
      parameters: { type: 'object', properties: { path: { type: 'string' },
        ...(toolName.endsWith('write_file') ? { content: { type: 'string' } } : {}) },
        required: toolName.endsWith('write_file') ? ['path', 'content'] : ['path'], additionalProperties: false },
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: String(value) }] },
      execute: (args: unknown, exec: ToolRunContext) => new Promise((resolve, reject) => {
        const turn = exec.agent && active.get(exec.agent.id);
        if (!turn || turn.cancelled || exec.signal.aborted || !bridge.connected) { reject(Error('Disconnected')); return; }
        const id = randomUUID();
        const abort = (): void => { cleanup(); pending.delete(id); reject(Error('Cancelled')); };
        const timer = setTimeout(() => { cleanup(); pending.delete(id); reject(Error('Tool approval timed out')); }, 125000);
        const cleanup = (): void => { clearTimeout(timer); exec.signal.removeEventListener('abort', abort); };
        pending.set(id, { turn, resolve: (value) => { cleanup(); resolve(value); },
          reject: (error) => { cleanup(); reject(error); } });
        exec.signal.addEventListener('abort', abort, { once: true });
        try { emit(turn, 'tool.request', { callId: id, name: toolName, arguments: object(args) }); }
        catch { cleanup(); pending.delete(id); reject(Error('Disconnected')); }
      }),
    });
  }
  ctx.on('agent/assistant-stream', ({ agent, frame }) => {
    const turn = active.get(agent.id);
    if (!turn || turn.cancelled || !bridge.connected || frame.type !== 'chunk') return;
    if (frame.chunk.type === 'text-delta') emit(turn, 'text.delta', { text: frame.chunk.text });
    if (frame.chunk.type === 'usage') emit(turn, 'usage', { usage: frame.chunk.usage });
  });
  ctx.on('session/event', (session, event) => {
    const turn = active.get(session.id);
    if (!turn || turn.cancelled || !bridge.connected) return;
    if (event.type === 'assistant/message') {
      emit(turn, 'text.final', { text: event.data.message.content.filter((b) => b.type === 'text').map((b) => b.text).join('') });
    }
  });
  ctx.effect(() => async () => {
    await bridge.close();
    await Promise.allSettled([...handles.values()].map((handle) => handle.dispose()));
  });
  await bridge.start();
}
