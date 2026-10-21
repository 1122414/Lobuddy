// AudioWorklet: 32 ms / 512 samples at a required 16 kHz, mono PCM16.
class VoiceCapture extends AudioWorkletProcessor {
  constructor() { super(); this.samples = new Int16Array(512); this.offset = 0; }
  process(inputs) {
    const input = inputs[0]?.[0];
    if (input) for (const value of input) {
      this.samples[this.offset++] = Math.round(Math.max(-1, Math.min(1, value)) * 32767);
      if (this.offset === 512) {
        this.port.postMessage(this.samples.buffer, [this.samples.buffer]);
        this.samples = new Int16Array(512); this.offset = 0;
      }
    }
    // Outputs remain zero, so microphone audio is never routed to speakers.
    return true;
  }
}
registerProcessor('voice-capture', VoiceCapture);
