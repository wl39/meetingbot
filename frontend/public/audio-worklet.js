class PCMCollector extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buffer = new Float32Array(Math.round(sampleRate * 0.15));
    this.offset = 0;
    this.stopped = false;
    this.port.onmessage = ({ data }) => {
      if (data === "stop") {
        this.stopped = true;
        this.flush();
        this.port.postMessage({ type: "flushed" });
      }
    };
  }
  flush() {
    if (this.offset) {
      const samples = this.buffer.slice(0, this.offset);
      this.port.postMessage({ type: "audio", samples }, [samples.buffer]);
      this.offset = 0;
    }
  }
  process(inputs, outputs) {
    // Keep the node rendering with silent output, avoiding microphone feedback.
    outputs.forEach((output) => output.forEach((channel) => channel.fill(0)));
    if (this.stopped) return false;
    const channels = inputs[0];
    if (!channels || !channels.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let value = 0;
      for (const channel of channels) value += channel[i] / channels.length;
      this.buffer[this.offset++] = value;
      if (this.offset === this.buffer.length) this.flush();
    }
    return true;
  }
}
registerProcessor("pcm-collector", PCMCollector);
