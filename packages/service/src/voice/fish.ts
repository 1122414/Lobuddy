import { request } from 'node:https';
import type { IncomingMessage } from 'node:http';
import type { VoiceOptions } from '@lobuddy/contracts';
export const FISH_VOICE = 'e4a66454f7a44f63a2cc9e8c044d701d';
export class FishError extends Error {}
export type Synthesizer = (text: string,key: string,model: VoiceOptions['fish_model'],signal: AbortSignal) => AsyncIterable<Buffer>;
type FishResponse = AsyncIterable<Uint8Array> & { statusCode?: number; destroy(): void };
export type FishConnection = (body: Buffer,key: string,model: VoiceOptions['fish_model'],signal: AbortSignal) => Promise<FishResponse>;
const connect: FishConnection = (body,key,model,signal) => new Promise<IncomingMessage>((resolve,reject) => {
  const call = request('https://api.fish.audio/v1/tts',{ method: 'POST',agent: false,signal,
    headers: { Authorization: 'Bearer ' + key,model,'Content-Type': 'application/json','Content-Length': body.length } },resolve);
  call.setTimeout(30000,() => call.destroy(Error('timeout'))); call.on('error',reject); call.end(body);
});
export function fishSynthesizer(connection: FishConnection = connect): Synthesizer {
return async function* (text,key,model,owner) {
  if (!key) throw new FishError('请先配置 Fish Audio 凭据');
  const timeout = new AbortController(),timer = setTimeout(() => timeout.abort(),180000);
  const signal = AbortSignal.any([owner,timeout.signal]);
  let response: FishResponse | undefined;
  try {
    const body = Buffer.from(JSON.stringify({ text,reference_id: FISH_VOICE,format: 'pcm',sample_rate: 24000,latency: 'balanced' }));
    response = await connection(body,key,model,signal);
    if (response.statusCode !== 200) {
      const messages: Record<number,string> = { 401: 'Fish 凭据无效，请重新配置',402: 'Fish API 额度独立于网页积分，请检查 API 计费或选择免费档',404: '选定音色不可用，未更换音色',429: 'Fish 请求过于频繁，请稍后重试' };
      throw new FishError(messages[response.statusCode ?? 0] ?? 'Fish 合成暂不可用，未更换音色');
    }
    let count = 0,pending = Buffer.alloc(0);
    for await (const chunk of response) {
      signal.throwIfAborted(); const bytes = Buffer.from(chunk); count += bytes.length;
      if (count > 24000 * 2 * 180) throw new FishError('合成音频超过单轮上限');
      pending = Buffer.concat([pending,bytes]);
      while (pending.length >= 4096) { yield pending.subarray(0,4096); pending = pending.subarray(4096); }
    }
    if (!count || pending.length % 2) throw new FishError('Fish 未返回完整音频，未更换音色');
    if (pending.length) yield pending;
  } catch (error) { owner.throwIfAborted(); if (error instanceof FishError) throw error; throw new FishError('Fish 连接中断，请检查网络；未自动重试'); }
  finally { clearTimeout(timer); response?.destroy(); }
};
}
export const synthesize = fishSynthesizer();
export function spokenText(text: string): string {
  const clean = text.replace(/```[\s\S]*?(?:```|$)/g,'').replace(/`[^`]*`|!\[[^\]]*\]\([^)]*\)/g,'')
    .replace(/\[([^\]]*)\]\([^)]*\)/g,'$1').replace(/[*#_>|]/g,'').trim();
  return /[\p{L}\p{N}]/u.test(clean) ? clean : '';
}
