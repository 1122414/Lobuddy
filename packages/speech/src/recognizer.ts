import type { Tensor } from 'onnxruntime-node';
import { join } from 'node:path';
import type { SpeechEvent } from './protocol.js';
export interface AudioRecognizer {
  probability(frame: Float32Array): Promise<number>;
  transcribe(audio: Float32Array): Promise<string>;
  close(): Promise<void>;
}
export async function loadRecognizer(root: string): Promise<AudioRecognizer> {
  // Set before importing the native binding: later API calls cannot undo its initialization.
  process.env.ORT_DISABLE_TELEMETRY = '1';
  const ort = await import('onnxruntime-node');
  const vad = await ort.InferenceSession.create(join(root,'silero.onnx'),{ executionProviders: ['cpu'],intraOpNumThreads: 1,interOpNumThreads: 1 });
  try {
    const { env,pipeline } = await import('@huggingface/transformers'); env.allowRemoteModels = false; env.useBrowserCache = false;
    const asr = await pipeline('automatic-speech-recognition',join(root,'whisper-small'),{
      device: 'cpu',dtype: 'q8',local_files_only: true,session_options: { intraOpNumThreads: 4,interOpNumThreads: 1 },
    });
    let h: Tensor = new ort.Tensor('float32',new Float32Array(128),[1,1,128]),c: Tensor = new ort.Tensor('float32',new Float32Array(128),[1,1,128]);
    let context = new Float32Array(64);
    return {
      probability: async frame => {
        const input = new Float32Array(576); input.set(context); input.set(frame,64);
        const result = await vad.run({ input: new ort.Tensor('float32',input,[1,576]),h,c });
        h = result.hn!; c = result.cn!; context = frame.slice(-64);
        const value = Number(result.speech_probs!.data[0]); if (!Number.isFinite(value) || !h || !c) throw Error('VAD 结果无效'); return value;
      },
      transcribe: async audio => {
        const value = await asr(audio,{ language: 'chinese',task: 'transcribe',num_beams: 1,do_sample: false,max_new_tokens: 128 });
        return value.text.trim().slice(0,4000);
      },close: async () => { await asr.dispose(); await vad.release(); },
    };
  } catch (error) { await vad.release(); throw error; }
}
export class AudioSession {
  private frames: Float32Array[] = [];
  private previous: Float32Array[] = [];
  private voiced = 0;
  private silent = 0;
  private active = false;
  private round = 0;
  private closed = false;
  private queued = 0;
  private tail = Promise.resolve();
  private pending?: Promise<void>;
  constructor(private readonly recognizer: AudioRecognizer,private readonly silenceMs: number,
    readonly generation: number,private readonly emit: (event: SpeechEvent) => void) {}
  frame(pcm: string): Promise<void> {
    if (this.closed) return Promise.reject(Error('识别已结束'));
    const bytes = Buffer.from(pcm,'base64'); if (bytes.length !== 1024 || bytes.toString('base64') !== pcm) return Promise.reject(Error('音频帧无效'));
    if (this.queued >= 32) { this.fail('overload'); return Promise.reject(Error('识别队列已满')); }
    const audio = new Float32Array(512); for (let i = 0; i < 512; i++) audio[i] = bytes.readInt16LE(i * 2) / 32768;
    this.queued++;
    const next = this.tail.then(async () => {
      if (this.closed) return;
      const probability = await this.recognizer.probability(audio); if (this.closed) return;
      this.previous.push(audio); if (this.previous.length > 10) this.previous.shift();
      this.voiced = probability >= .6 ? this.voiced + 1 : 0;
      if (!this.active && this.voiced >= 3) {
        this.round++; this.active = true; this.silent = 0; this.frames = [...this.previous]; this.send('speech');
      } else if (this.active) {
        this.frames.push(audio); this.silent = probability < .35 ? this.silent + 32 : 0;
        if (this.silent >= this.silenceMs || this.frames.length >= 938) {
          this.active = false; this.voiced = 0;
          if (this.pending) { this.fail('overload'); return; }
          const merged = new Float32Array(this.frames.length * 512); this.frames.forEach((frame,index) => merged.set(frame,index * 512)); this.frames = [];
          const round = this.round;
          this.pending = this.recognizer.transcribe(merged).then(text => {
            if (!this.closed && round === this.round) this.send('transcript',text);
          },() => { if (!this.closed && round === this.round) this.fail('error'); }).finally(() => { merged.fill(0); this.pending = undefined; });
        }
      }
    }).catch(() => { this.fail('error'); }).finally(() => { this.queued--; });
    this.tail = next; return next;
  }
  private send(kind: SpeechEvent['kind'],text = '') { this.emit({ kind,generation: this.generation,round: this.round,text }); }
  private fail(kind: 'error' | 'overload') { if (this.closed) return; this.send(kind); this.closed = true; this.frames = []; this.previous = []; }
  async close(): Promise<void> { this.closed = true; this.frames = []; this.previous = []; await this.tail; await this.pending; await this.recognizer.close(); }
}
