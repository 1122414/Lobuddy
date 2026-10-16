import type { Context } from '@deepseek-ai/cordis';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { text, type ObjectValue } from './transport.js';

/** One auxiliary call, no tools, history or agent retry loop. Python owns its budget. */
export class AnalysisCalls {
  private active = new Map<string, AbortController>();
  constructor(private ctx: Context) {}
  cancel(id?: string): void {
    for (const [key, controller] of this.active) if (!id || id === key) controller.abort();
  }
  async run(params: ObjectValue): Promise<ObjectValue> {
    const id = text(params.id, 128);
    const prompt = text(params.prompt, 8000);
    if (Buffer.byteLength(prompt, 'utf8') > 7000 || this.active.size) throw Error('Analysis unavailable');
    const controller = new AbortController();
    this.active.set(id, controller);
    const timer = setTimeout(() => controller.abort(), 45000);
    try {
      let output = ''; let complete = false;
      for await (const chunk of this.ctx.llm.stream({
        provider: text(process.env.LOBUDDY_DSH_PROVIDER), model: text(process.env.LOBUDDY_DSH_MODEL),
        messages: [createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: prompt }] })],
        maxTokens: 1024, tools: [], signal: controller.signal,
      })) {
        if (chunk.type === 'text-delta') output += chunk.text;
        if (output.length > 16000) throw Error('Analysis output exceeded');
        if (chunk.type === 'finish') {
          if (chunk.reason.kind !== 'stop') throw Error('Analysis incomplete');
          complete = true;
        }
      }
      if (!complete || controller.signal.aborted) throw Error('Analysis incomplete');
      return { text: output };
    } finally { clearTimeout(timer); this.active.delete(id); }
  }
}
