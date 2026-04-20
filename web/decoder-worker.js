import { SAMEStreamDecoder, decodeSamePcm } from "./decoder-core.js";

let streamDecoder = new SAMEStreamDecoder();

self.onmessage = (event) => {
  const { type } = event.data;

  try {
    switch (type) {
      case "decode-offline": {
        const { samples, sampleRate, sourceLabel, sourceKind } = event.data;
        const result = decodeSamePcm(samples, sampleRate, { minRepeats: 1 });
        self.postMessage({
          type: "offline-results",
          sourceLabel,
          sourceKind,
          alerts: result.alerts,
          bursts: result.bursts,
        });
        break;
      }
      case "start-stream": {
        streamDecoder = new SAMEStreamDecoder();
        self.postMessage({
          type: "status",
          level: "info",
          message: `Monitoring ${event.data.sourceLabel || "live source"} in real time.`,
        });
        break;
      }
      case "append-stream-samples": {
        const { samples, sampleRate } = event.data;
        const ready = streamDecoder.appendPcm(samples, sampleRate);
        if (ready) {
          const result = streamDecoder.scan();
          self.postMessage({
            type: "stream-results",
            alerts: result.alerts,
            bursts: result.bursts,
          });
        }
        break;
      }
      case "stop-stream": {
        streamDecoder.reset();
        self.postMessage({
          type: "status",
          level: "info",
          message: "Live monitoring stopped.",
        });
        break;
      }
      default:
        self.postMessage({
          type: "status",
          level: "warn",
          message: `Unknown worker message type: ${type}`,
        });
    }
  } catch (error) {
    self.postMessage({
      type: "error",
      message: error instanceof Error ? error.message : String(error),
    });
  }
};
