class ServerPlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.readIndex = 0;
    this.maxBufferedFrames = Math.max(4096, Math.round(sampleRate * 3.0));
    this.resumeBufferedFrames = Math.max(2048, Math.round(sampleRate * 2.0));
    this.lowWaterFrames = Math.max(1024, Math.round(sampleRate * 0.75));
    this.buffering = true;

    this.port.onmessage = (event) => {
      const { type, samples } = event.data;
      if (type === "reset") {
        this.queue = [];
        this.readIndex = 0;
        this.buffering = true;
        return;
      }
      if (type === "append-samples" && samples) {
        this.queue.push(samples);
        this.trimQueue();
      }
    };
  }

  trimQueue() {
    let totalFrames = this.bufferedFrames();

    while (this.queue.length > 1 && totalFrames > this.maxBufferedFrames) {
      const dropped = this.queue.shift();
      totalFrames -= dropped.length;
      this.readIndex = 0;
    }
  }

  bufferedFrames() {
    let totalFrames = -this.readIndex;
    for (const chunk of this.queue) {
      totalFrames += chunk.length;
    }
    return Math.max(0, totalFrames);
  }

  process(inputs, outputs) {
    const output = outputs[0][0];
    output.fill(0);

    const availableFrames = this.bufferedFrames();
    if (this.buffering) {
      if (availableFrames < this.resumeBufferedFrames) {
        return true;
      }
      this.buffering = false;
    } else if (availableFrames < this.lowWaterFrames) {
      this.buffering = true;
      return true;
    }

    let writeIndex = 0;
    while (writeIndex < output.length && this.queue.length) {
      const chunk = this.queue[0];
      const available = chunk.length - this.readIndex;
      const toCopy = Math.min(output.length - writeIndex, available);
      output.set(chunk.subarray(this.readIndex, this.readIndex + toCopy), writeIndex);
      writeIndex += toCopy;
      this.readIndex += toCopy;

      if (this.readIndex >= chunk.length) {
        this.queue.shift();
        this.readIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor("server-playback-processor", ServerPlaybackProcessor);
