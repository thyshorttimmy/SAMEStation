class AudioCaptureProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (!channels || channels.length === 0) {
      return true;
    }

    const frameCount = channels[0].length;
    const mono = new Float32Array(frameCount);

    for (let channelIndex = 0; channelIndex < channels.length; channelIndex += 1) {
      const channel = channels[channelIndex];
      for (let frame = 0; frame < frameCount; frame += 1) {
        mono[frame] += channel[frame];
      }
    }

    const scale = 1 / channels.length;
    for (let frame = 0; frame < frameCount; frame += 1) {
      mono[frame] *= scale;
    }

    this.port.postMessage({ samples: mono }, [mono.buffer]);
    return true;
  }
}

registerProcessor("audio-capture-processor", AudioCaptureProcessor);
