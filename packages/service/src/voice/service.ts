import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { VoiceStatusSchema,VoiceOptionsSchema,type VoiceStatus,type VoiceOptions,type VoiceEvent,type VoiceFrame,type VoicePoll,type TurnState } from '@lobuddy/contracts';
import type { SpeechDriver,SpeechEvent } from '@lobuddy/speech';
import { Store } from '../storage/database.js';
import { parseStoredJson } from '../storage/json.js';
import { synthesize,spokenText,FishError,type Synthesizer } from './fish.js';
type Hooks = { submit: (session: string,text: string,id: string) => Promise<TurnState>; cancel: (id: string) => Promise<unknown>; prepare: () => Promise<void> };
export class VoiceService {
  readonly status: VoiceStatus;
  private options: VoiceOptions;
  private events: VoiceEvent[] = [];
  private sequence = 0;
  private frameSequence = 0;
  private generation = 0;
  private round = 0;
  private baseRound = 0;
  private workerRound = 0;
  private transcriptIdentity = '';
  private turn = '';
  private text = '';
  private sent = 0;
  private queue: (string | null)[] = [];
  private speaker?: Promise<void>;
  private speaking?: AbortController;
  private transition = Promise.resolve();
  private cancellation = Promise.resolve();
  private lease = 0;
  private watchdog?: ReturnType<typeof setInterval>;
  private downloading?: Promise<void>;
  private loading?: Promise<void>;
  private closed = false;
  private changing = 0;
  constructor(private readonly store: Store,private readonly driver: SpeechDriver | undefined,
    private readonly key: () => string,private readonly hooks: Hooks,private readonly tts: Synthesizer = synthesize,private readonly now = () => performance.now()) {
    const row = store.connection.prepare("SELECT value FROM app_settings WHERE key='voice_options'").get();
    this.options = VoiceOptionsSchema.parse(row ? parseStoredJson(String(row.value)) : {});
    this.status = VoiceStatusSchema.parse({ ...this.options,fish_configured: Boolean(key()) });
    if (driver) { driver.event = event => this.receive(event); driver.fault = () => { if (this.status.voice_id && !['off','muted','error'].includes(this.status.state)) this.fail('本地语音进程中断，请重新开启'); }; }
  }
  get active() { return Boolean(this.status.voice_id); }
  view() { this.status.fish_configured = Boolean(this.key()); return VoiceStatusSchema.parse(this.status); }
  async initialize() { if (this.driver) this.status.model_ready = await this.driver.request({ kind: 'check' }).catch(() => false); }
  configure(options: VoiceOptions) {
    if (this.active || this.status.downloading) throw Error('请先结束语音或下载再修改设置'); this.options = VoiceOptionsSchema.parse(options);
    this.store.run('INSERT INTO app_settings VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at','voice_options',JSON.stringify(this.options),new Date().toISOString());
    Object.assign(this.status,this.options); return this.view();
  }
  download() {
    if (!this.driver) { this.status.error = '本地语音进程不可用'; return this.view(); }
    if (this.active) throw Error('请先结束语音再下载模型');
    if (!this.downloading && !this.status.model_ready) {
      this.status.downloading = true; this.status.error = '';
      this.downloading = this.driver.request({ kind: 'download' }).then(ready => { this.status.model_ready = ready; },() => {
        this.status.error = '本地模型下载或校验失败，请检查网络后重试；文字仍可用';
      }).finally(() => { this.status.downloading = false; this.downloading = undefined; });
    } return this.view();
  }
  start(session: string) {
    if (this.closed || this.active || this.changing) throw Error('已有语音会话或服务正在切换');
    if (!this.driver || !this.status.model_ready || this.status.downloading || !this.key()) {
      this.status.error = !this.driver ? '本地语音进程不可用' : !this.status.model_ready ? '请先在设置中下载本地语音模型' : !this.key() ? '请先配置 Fish Audio 凭据' : '正在下载模型'; return this.view();
    }
    this.status.voice_id = randomUUID(); this.status.session_id = session; this.status.state = 'loading'; this.status.error = '';
    this.sequence = this.round = this.workerRound = this.frameSequence = 0; this.events = []; this.lease = this.now();
    this.watchdog = setInterval(() => { if (this.now() - this.lease > 5000) void this.stop(); },1000); this.watchdog.unref();
    this.load(); return this.view();
  }
  private load() {
    const generation = ++this.generation; this.baseRound = this.round; this.workerRound = 0;
    this.loading = (async () => {
      await this.hooks.prepare(); if (generation !== this.generation) return;
      await this.driver!.request({ kind: 'start',generation,silence_ms: this.options.silence_ms });
      if (generation === this.generation && this.status.state === 'loading') this.status.state = 'listening';
    })().catch(() => { if (generation === this.generation) this.fail('语音或模型服务准备失败，请结束语音后重新开启'); });
  }
  check(id: string) { if (!id || id !== this.status.voice_id) throw Error('语音会话已失效'); }
  async frame(params: VoiceFrame) {
    this.check(params.voice_id);
    if (['loading','muted','off','error'].includes(this.status.state) || params.sequence <= this.frameSequence) return { accepted: false };
    if (params.sequence !== this.frameSequence + 1) { this.fail('音频帧丢失，请重新开启语音'); return { accepted: false }; }
    const bytes = Buffer.from(params.pcm,'base64'); if (bytes.length !== 1024 || bytes.toString('base64') !== params.pcm) throw Error('音频帧无效');
    this.frameSequence = params.sequence; const generation = this.generation;
    try { await this.driver!.request({ kind: 'frame',generation,pcm: params.pcm }); return { accepted: generation === this.generation }; }
    catch { if (generation === this.generation) this.fail('音频识别连接中断，请重新开启'); return { accepted: false }; }
  }
  poll(params: VoicePoll) {
    this.check(params.voice_id); this.lease = this.now();
    if (params.after > this.sequence) throw Error('语音事件序号无效');
    this.events = this.events.filter(event => event.sequence > params.after);
    if (params.playing && this.status.state === 'listening') this.status.state = 'speaking';
    else if (!params.playing && this.status.state === 'speaking' && !this.speaker) this.status.state = 'listening';
    return { status: this.view(),events: this.events.map(event => ({ ...event })) };
  }
  private emit(kind: VoiceEvent['kind'],text = '',pcm = '') {
    if (this.events.length >= 128) { this.fail('音频播放端未及时响应，请重新开启语音'); return; }
    this.events.push({ voice_id: this.status.voice_id,session_id: this.status.session_id,turn_id: this.turn,round_id: this.round,sequence: ++this.sequence,kind,text,pcm,sample_rate: 24000 });
  }
  private invalidate(clear: boolean) {
    this.speaking?.abort(); this.speaking = undefined; this.speaker = undefined; this.queue = [];
    const old = this.turn; this.turn = ''; this.text = ''; this.sent = 0; if (clear) this.events = [];
    if (old) this.cancellation = this.cancellation.then(() => this.hooks.cancel(old)).then(() => {},() => {});
  }
  private fail(message: string) {
    if (['error','off'].includes(this.status.state)) return;
    this.status.state = 'error'; this.status.error = message; this.generation++; this.invalidate(true);
    this.emit('error',message); void this.driver?.request({ kind: 'stop' }).catch(() => {});
  }
  private receive(event: SpeechEvent) {
    if (event.generation !== this.generation || ['off','muted','loading','error'].includes(this.status.state)) return;
    if (event.kind === 'speech') {
      if (event.round <= this.workerRound) return; this.workerRound = event.round; this.round = this.baseRound + event.round;
      this.invalidate(true); this.emit('interrupt'); this.status.state = 'listening'; return;
    }
    if (event.round !== this.workerRound) return;
    if (event.kind === 'error' || event.kind === 'overload') { this.fail('本地识别未完成，请稍后再说；未发送不完整文字'); return; }
    const text = event.text.trim(); if (!text) return;
    const identity = `${event.generation}:${event.round}`;
    if (identity === this.transcriptIdentity) return; this.transcriptIdentity = identity;
    const generation = this.generation,round = this.round,session = this.status.session_id,id = `voice-${this.status.voice_id}-${round}`;
    this.status.state = 'thinking'; this.emit('transcript',text);
    void (async () => {
      await this.cancellation; if (generation !== this.generation || round !== this.round) return;
      const state = await this.hooks.submit(session,text,id);
      if (generation !== this.generation || round !== this.round) { await this.hooks.cancel(state.turn_id); return; }
      this.turn = state.turn_id; this.text = ''; this.sent = 0; this.queue = []; const owner = this.speaking = new AbortController();
      const speaker = this.speak(round,state.turn_id,owner.signal); this.speaker = speaker;
      void speaker.finally(() => { if (this.speaker === speaker) this.speaker = undefined; }).catch(() => {});
      if (state.output_text) this.turnEvent(state.turn_id,'text.final',state.output_text);
      if (!['queued','running'].includes(state.status)) this.turnEvent(state.turn_id,'turn.' + state.status,state.output_text);
    })().catch(() => { if (generation === this.generation && round === this.round) this.fail('本轮对话未完成，请查看文字任务状态'); });
  }
  turnEvent(id: string,kind: string,output: string) {
    if (id !== this.turn || !this.speaking || this.speaking.signal.aborted) return;
    if (this.queue.length >= 30) { this.fail('回答超过语音播放容量，文字结果仍可查看'); return; }
    if (kind === 'text.delta' || kind === 'text.final') {
      this.text = output; if ((this.text.match(/```/g)?.length ?? 0) % 2) return;
      const ends = [...this.text.slice(this.sent).matchAll(/[。！？!?\n]/g)],last = ends.at(-1);
      if (last) { const end = this.sent + last.index + last[0].length; this.queue.push(this.text.slice(this.sent,end)); this.sent = end; }
    } else if (kind === 'turn.completed') { this.queue.push(output.slice(this.sent),null); }
    else if (kind === 'turn.cancelled') { this.invalidate(true); this.emit('interrupt'); this.status.state = 'listening'; }
    else if (kind === 'turn.failed' || kind === 'turn.interrupted') this.fail('本轮模型对话未完成，请查看文字任务状态后重试');
  }
  private async speak(round: number,turn: string,signal: AbortSignal) {
    const current = () => !signal.aborted && round === this.round && turn === this.turn && !['error','muted','off'].includes(this.status.state);
    try {
      while (current()) {
        if (!this.queue.length) { await delay(20,undefined,{ signal }); continue; }
        const item = this.queue.shift(); if (item === null) { this.emit('audio.end'); this.status.state = 'listening'; return; }
        const text = spokenText(item ?? ''); if (!text) continue;
        for await (const pcm of this.tts(text,this.key(),this.options.fish_model,signal)) {
          while (this.events.length >= 96 && current()) await delay(20,undefined,{ signal });
          if (!current()) return;
          if (pcm.length % 2 || pcm.length > 4096) throw new FishError('收到不完整的语音数据');
          this.status.state = 'speaking'; this.emit('audio','',pcm.toString('base64'));
        }
      }
    } catch (error) { if (current()) this.fail(error instanceof FishError ? error.message : '语音合成中断，未自动重试'); }
  }
  mute(id: string,muted: boolean): Promise<VoiceStatus> {
    this.check(id); this.generation++; this.round++; this.status.state = 'muted'; this.invalidate(true); this.emit('interrupt'); this.frameSequence = 0;
    this.changing++;
    const generation = this.generation;
    const result = this.transition.then(async () => {
      await this.driver?.request({ kind: 'stop' }).catch(() => {}); await this.loading; await this.cancellation;
      if (generation === this.generation && !muted) { this.status.state = 'loading'; this.load(); } return this.view();
    }).finally(() => { this.changing--; }); this.transition = result.then(() => {},() => {}); return result;
  }
  stop(): Promise<VoiceStatus> {
    this.changing++;
    this.generation++; this.status.state = 'off'; this.invalidate(true); clearInterval(this.watchdog); this.watchdog = undefined;
    this.status.voice_id = this.status.session_id = ''; this.frameSequence = 0;
    const result = this.transition.then(async () => { await this.driver?.request({ kind: 'stop' }).catch(() => {}); await this.loading; await this.cancellation; return this.view(); }).finally(() => { this.changing--; });
    this.transition = result.then(() => {},() => {}); return result;
  }
  async close() { this.closed = true; await this.stop(); await this.driver?.close(); await this.downloading; }
}
