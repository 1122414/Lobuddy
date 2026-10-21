import { request } from './api';
import type { VoiceStatus } from '../../shared/desktop-protocol';

export class VoiceController {
  private stream?: MediaStream;
  private context?: AudioContext;
  private source?: MediaStreamAudioSourceNode;
  private capture?: AudioWorkletNode;
  private playing = new Set<AudioBufferSourceNode>();
  private nextTime = 0;
  private voice = '';
  private cursor = 0;
  private round = 0;
  private frame = 0;
  private captureQueue = { pending: 0, tail: Promise.resolve() };
  private generation = 0;
  private revision = 0;
  private timer?: ReturnType<typeof setTimeout>;
  private alive = false;
  private muted = false;
  constructor(private update: (status: VoiceStatus | null, error?: string) => void) {}
  async start(session: string) {
    if (this.alive) return;
    const revision = ++this.revision;
    this.alive = true; this.muted = false;
    try {
      const permitted = await window.lobuddy?.voicePermission();
      if (!this.alive || revision !== this.revision) return;
      if (!permitted) throw Error('麦克风未授权，请在系统设置中允许后重试。');
      const status = await request('voice.start', { session_id: session });
      if (!this.alive || revision !== this.revision) return;
      this.voice = status.voice_id || '';
      if (!this.voice) throw Error(status.error || '语音尚未准备好，请查看设置。');
      this.cursor = this.round = this.frame = 0;
      this.update(status);
      await this.poll();
    } catch (error) { if (revision === this.revision) { await this.stop(); throw error; } }
  }
  private async microphone() {
    const generation = this.generation;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }, video: false });
    if (!this.alive || generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
    this.stream = stream;
    const context = new AudioContext({ sampleRate: 16000 });
    this.context = context;
    if (this.context.sampleRate !== 16000) throw Error('音频设备不支持本地识别所需的采样率。');
    await context.audioWorklet.addModule('/voice-capture.js');
    if (!this.alive || generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); await context.close(); return; }
    await context.resume();
    if (!this.alive || generation !== this.generation) { stream.getTracks().forEach(track => track.stop()); return; }
    this.capture = new AudioWorkletNode(context, 'voice-capture');
    this.source = context.createMediaStreamSource(stream);
    this.source.connect(this.capture); this.capture.connect(context.destination);
    for (const track of stream.getTracks()) track.onended = () => { void this.fail('麦克风已断开，请重新选择系统输入设备后开启。'); };
    this.capture.port.onmessage = event => this.captureFrame(event.data as ArrayBuffer, generation);
  }
  private captureFrame(data: ArrayBuffer, generation: number) {
    if (!this.alive || generation !== this.generation) return;
    const queue = this.captureQueue;
    // One second of PCM absorbs short renderer/IPC bursts; sustained overload still stops.
    if (queue.pending >= 32) { void this.fail('音频处理跟不上采集，已停止；请重新开启。'); return; }
    const bytes = new Uint8Array(data);
    const pcm = btoa(String.fromCharCode(...bytes));
    const sequence = ++this.frame, voice_id = this.voice;
    queue.pending++;
    queue.tail = queue.tail.then(async () => {
      if (generation !== this.generation || !this.alive) return;
      await request('voice.frame', { voice_id, sequence, pcm });
    }).catch(() => { if (generation === this.generation && this.alive) void this.fail('语音连接中断，请重新开启。'); }).finally(() => { queue.pending--; });
  }
  private stopPlayback() {
    for (const source of this.playing) { try { source.stop(); } catch { /* Already ended. */ } source.disconnect(); }
    this.playing.clear(); this.nextTime = 0;
  }
  private release() {
    this.generation++;
    this.captureQueue = { pending: 0, tail: Promise.resolve() };
    this.stopPlayback();
    this.capture?.disconnect(); this.source?.disconnect();
    this.capture = undefined; this.source = undefined;
    this.stream?.getTracks().forEach(track => { track.onended = null; track.stop(); }); this.stream = undefined;
    void this.context?.close(); this.context = undefined;
  }
  private play(pcm: string, rate: number) {
    const context = this.context;
    if (!context) return;
    const bytes = Uint8Array.from(atob(pcm), c => c.charCodeAt(0));
    if (bytes.length % 2) throw Error('收到不完整的语音数据。');
    if (this.nextTime - context.currentTime > 45) throw Error('语音播放队列过长，已停止。');
    const samples = new DataView(bytes.buffer);
    const buffer = context.createBuffer(1, bytes.length / 2, rate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < channel.length; index++) channel[index] = samples.getInt16(index * 2, true) / 32768;
    const source = context.createBufferSource(); source.buffer = buffer; source.connect(context.destination);
    source.onended = () => { this.playing.delete(source); source.disconnect(); };
    this.playing.add(source);
    const when = Math.max(context.currentTime + .01, this.nextTime);
    source.start(when); this.nextTime = when + buffer.duration;
  }
  private async poll() {
    if (!this.alive) return;
    const revision = this.revision;
    try {
      const result = await request('voice.poll', { voice_id: this.voice, after: this.cursor, playing: this.playing.size > 0 });
      if (!this.alive || revision !== this.revision) return;
      this.update(result.status);
      if (result.status.state === 'error') { await this.fail(result.status.error || '语音暂不可用。'); return; }
      if (result.status.state === 'listening' && !this.stream && !this.muted) await this.microphone();
      if (!this.alive || revision !== this.revision) return;
      for (const event of result.events) {
        if (event.voice_id !== this.voice || event.sequence <= this.cursor) continue;
        this.cursor = event.sequence;
        if (event.round_id < this.round) continue;
        if (event.kind === 'interrupt' || event.round_id > this.round) { this.stopPlayback(); this.round = event.round_id; }
        if (event.kind === 'audio' && event.round_id === this.round) this.play(event.pcm || '', event.sample_rate || 24000);
        if (event.kind === 'error') { await this.fail(event.text || '语音暂不可用'); return; }
      }
      if (this.alive) this.timer = setTimeout(() => { void this.poll(); }, 40);
    } catch { if (revision === this.revision) await this.fail('语音连接中断，请重新开启。'); }
  }
  async mute(muted: boolean) {
    // Local stop precedes RPC cancellation and prevents stale queued PCM from replaying.
    const revision = ++this.revision;
    this.muted = true; clearTimeout(this.timer);
    this.release(); this.frame = 0;
    if (!this.alive) return;
    try {
      const status = await request('voice.mute', { voice_id: this.voice, muted });
      if (!this.alive || revision !== this.revision) return;
      this.muted = muted; this.update(status);
      await this.poll();
    } catch (error) { if (revision === this.revision) { await this.stop(); throw error; } }
  }
  private async fail(message: string) { await this.stop(); this.update(null, message); }
  async stop() {
    const revision = ++this.revision;
    const wasAlive = this.alive;
    this.alive = false; this.muted = true; clearTimeout(this.timer); this.release(); this.voice = '';
    if (wasAlive) await request('voice.stop', {}).catch(() => undefined);
    if (revision === this.revision) this.update(null);
  }
}
