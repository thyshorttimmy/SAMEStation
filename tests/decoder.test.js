import test from "node:test";
import assert from "node:assert/strict";

import { decodeSamePcm, parseSameHeader } from "../web/decoder-core.js";

const BIT_DURATION_SECONDS = 1 / 520.8333333333334;
const SPACE_FREQUENCY = 1562.5;
const MARK_FREQUENCY = 2083.3333333333335;

test("parseSameHeader extracts originator, event, duration, and locations", () => {
  const parsed = parseSameHeader("ZCZC-WXR-TOR-048439+0030-1091415-KDDC/NWS-");
  assert.ok(parsed);
  assert.equal(parsed.originatorCode, "WXR");
  assert.equal(parsed.eventCode, "TOR");
  assert.equal(parsed.durationMinutes, 30);
  assert.equal(parsed.locations.length, 1);
  assert.equal(parsed.locations[0].stateCode, "48");
  assert.equal(parsed.locations[0].countyCode, "439");
  assert.equal(parsed.sender, "KDDC/NWS");
});

test("decodeSamePcm recovers a repeated SAME header from synthetic 48 kHz audio", () => {
  const header = "ZCZC-WXR-SVR-020013-020027+0045-1091415-KCLE/NWS-";
  const samples = generateRepeatedSameSignal(header, {
    sampleRate: 48000,
    repeats: 3,
    gapSeconds: 0.7,
    noiseAmplitude: 0.01,
    phaseOffset: 0.73,
  });

  const result = decodeSamePcm(samples, 48000, { minRepeats: 2 });
  assert.equal(result.alerts.length, 1);
  assert.equal(result.alerts[0].rawHeader, header);
  assert.equal(result.alerts[0].eventCode, "SVR");
  assert.ok(result.alerts[0].confidence > 0.4);
  assert.equal(result.alerts[0].repeatCount, 3);
});

test("decodeSamePcm ignores a fourth identical SAME header repeat in one burst group", () => {
  const header = "ZCZC-WXR-SVR-020013-020027+0045-1091415-KCLE/NWS-";
  const samples = generateRepeatedSameSignal(header, {
    sampleRate: 48000,
    repeats: 4,
    gapSeconds: 0.7,
    noiseAmplitude: 0.01,
    phaseOffset: 0.73,
  });

  const result = decodeSamePcm(samples, 48000, { minRepeats: 2 });
  assert.equal(result.alerts.length, 1);
  assert.equal(result.alerts[0].repeatCount, 3);
  assert.equal(result.alerts[0].rawBursts.filter((burst) => burst.kind === "header").length, 3);
});

function generateRepeatedSameSignal(
  header,
  {
    sampleRate = 48000,
    repeats = 3,
    gapSeconds = 1,
    leadSeconds = 0.3,
    tailSeconds = 0.3,
    noiseAmplitude = 0,
    phaseOffset = 0,
  } = {},
) {
  const sequence = [];
  const random = createSeededRandom(0x51aecd);
  for (let repeat = 0; repeat < repeats; repeat += 1) {
    sequence.push(...renderSilence(sampleRate, repeat === 0 ? leadSeconds : gapSeconds));
    sequence.push(...renderBurst(header, sampleRate, phaseOffset));
  }
  sequence.push(...renderSilence(sampleRate, tailSeconds));

  const output = new Float32Array(sequence.length);
  for (let index = 0; index < sequence.length; index += 1) {
    const noise = noiseAmplitude ? (random() * 2 - 1) * noiseAmplitude : 0;
    output[index] = sequence[index] + noise;
  }
  return output;
}

function renderBurst(header, sampleRate, phaseOffset) {
  const bytes = [];
  for (let index = 0; index < 16; index += 1) {
    bytes.push(0xab);
  }
  for (const character of header) {
    bytes.push(character.charCodeAt(0));
  }

  const bits = [];
  for (const value of bytes) {
    for (let bit = 0; bit < 8; bit += 1) {
      bits.push((value >> bit) & 1);
    }
  }

  const samplesPerBit = BIT_DURATION_SECONDS * sampleRate;
  const totalSamples = Math.ceil(bits.length * samplesPerBit);
  const signal = new Float32Array(totalSamples);

  for (let sampleIndex = 0; sampleIndex < totalSamples; sampleIndex += 1) {
    const time = sampleIndex / sampleRate;
    const bitIndex = Math.min(bits.length - 1, Math.floor(time / BIT_DURATION_SECONDS));
    const frequency = bits[bitIndex] ? MARK_FREQUENCY : SPACE_FREQUENCY;
    signal[sampleIndex] = 0.7 * Math.sin(2 * Math.PI * frequency * time + phaseOffset);
  }

  return Array.from(signal);
}

function renderSilence(sampleRate, seconds) {
  return Array.from(new Float32Array(Math.ceil(sampleRate * seconds)));
}

function createSeededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (1664525 * state + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}
