export const TARGET_SAMPLE_RATE = 12500;
export const BIT_SAMPLES = 24;
export const BIT_RATE = TARGET_SAMPLE_RATE / BIT_SAMPLES;
export const BIT0_FREQ = 1562.5;
export const BIT1_FREQ = 2083.3333333333335;
export const PREAMBLE_BYTE = 0xab;

const PREAMBLE_RUN_BYTES = 8;
const MAX_HEADER_BYTES = 280;
const ASCII_HEADER_RE = /^ZCZC-([A-Z0-9]{3})-([A-Z0-9]{3})-([0-9]{6}(?:-[0-9]{6})*)\+([0-9]{4})-([0-9]{7})-([A-Z0-9/ ]{1,16})-$/;
const SAME_CHAR_RE = /^[ A-Z0-9/+-]+$/;
const MIN_STREAM_REPEAT_COUNT = 2;
const STREAM_GROUP_SECONDS = 6;
const HEADER_REPEAT_TARGET = 3;

const ORIGINATORS = {
  CIV: "Civil authorities",
  EAS: "Broadcast station or cable system",
  PEP: "Primary Entry Point system",
  WXR: "National Weather Service",
};

const PARTITIONS = {
  0: "Entire area",
  1: "Northwest",
  2: "North",
  3: "Northeast",
  4: "West",
  5: "Central",
  6: "East",
  7: "Southwest",
  8: "South",
  9: "Southeast",
};

const STATES = {
  "01": "Alabama",
  "02": "Alaska",
  "04": "Arizona",
  "05": "Arkansas",
  "06": "California",
  "08": "Colorado",
  "09": "Connecticut",
  "10": "Delaware",
  "11": "District of Columbia",
  "12": "Florida",
  "13": "Georgia",
  "15": "Hawaii",
  "16": "Idaho",
  "17": "Illinois",
  "18": "Indiana",
  "19": "Iowa",
  "20": "Kansas",
  "21": "Kentucky",
  "22": "Louisiana",
  "23": "Maine",
  "24": "Maryland",
  "25": "Massachusetts",
  "26": "Michigan",
  "27": "Minnesota",
  "28": "Mississippi",
  "29": "Missouri",
  "30": "Montana",
  "31": "Nebraska",
  "32": "Nevada",
  "33": "New Hampshire",
  "34": "New Jersey",
  "35": "New Mexico",
  "36": "New York",
  "37": "North Carolina",
  "38": "North Dakota",
  "39": "Ohio",
  "40": "Oklahoma",
  "41": "Oregon",
  "42": "Pennsylvania",
  "44": "Rhode Island",
  "45": "South Carolina",
  "46": "South Dakota",
  "47": "Tennessee",
  "48": "Texas",
  "49": "Utah",
  "50": "Vermont",
  "51": "Virginia",
  "53": "Washington",
  "54": "West Virginia",
  "55": "Wisconsin",
  "56": "Wyoming",
  "60": "American Samoa",
  "66": "Guam",
  "69": "Northern Mariana Islands",
  "72": "Puerto Rico",
  "74": "U.S. Minor Outlying Islands",
  "78": "U.S. Virgin Islands",
};

const EVENTS = {
  ADR: "Administrative message",
  AVA: "Avalanche watch",
  AVW: "Avalanche warning",
  BHW: "Biological hazard warning",
  BLU: "Blue alert",
  BZW: "Blizzard warning",
  CAE: "Child abduction emergency",
  CDW: "Civil danger warning",
  CEM: "Civil emergency message",
  DMO: "Demo message",
  DSW: "Dust storm warning",
  EAN: "Emergency action notification",
  EAT: "Emergency action termination",
  EQW: "Earthquake warning",
  EVI: "Evacuation immediate",
  FFA: "Flash flood watch",
  FFW: "Flash flood warning",
  FLS: "Flood statement",
  FLA: "Flood watch",
  FLW: "Flood warning",
  FRW: "Fire warning",
  FZW: "Freeze warning",
  HLS: "Hurricane local statement",
  HUA: "Hurricane watch",
  HUW: "Hurricane warning",
  LAE: "Local area emergency",
  LEW: "Law enforcement warning",
  NIC: "National information center",
  NMN: "Network message notification",
  NPT: "National periodic test",
  NUW: "Nuclear power plant warning",
  RMT: "Required monthly test",
  RWT: "Required weekly test",
  SMW: "Special marine warning",
  SPS: "Special weather statement",
  SPW: "Shelter in place warning",
  SQW: "Snow squall warning",
  SSA: "Storm surge watch",
  SSW: "Storm surge warning",
  SVA: "Severe thunderstorm watch",
  SVR: "Severe thunderstorm warning",
  TOR: "Tornado warning",
  TOA: "Tornado watch",
  TSA: "Tsunami watch",
  TSW: "Tsunami warning",
  VOW: "Volcano warning",
  WSW: "Winter storm warning",
};

const BIT0_COS = [];
const BIT0_SIN = [];
const BIT1_COS = [];
const BIT1_SIN = [];

for (let n = 0; n < BIT_SAMPLES; n += 1) {
  const angle0 = (2 * Math.PI * 3 * n) / BIT_SAMPLES;
  const angle1 = (2 * Math.PI * 4 * n) / BIT_SAMPLES;
  BIT0_COS.push(Math.cos(angle0));
  BIT0_SIN.push(Math.sin(angle0));
  BIT1_COS.push(Math.cos(angle1));
  BIT1_SIN.push(Math.sin(angle1));
}

function appendFloat32(base, extra) {
  if (base.length === 0) {
    return extra.slice();
  }
  const merged = new Float32Array(base.length + extra.length);
  merged.set(base, 0);
  merged.set(extra, base.length);
  return merged;
}

export function formatDurationFromMinutes(totalMinutes) {
  if (!Number.isFinite(totalMinutes)) {
    return "Unknown";
  }
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours === 0) {
    return `${minutes} min`;
  }
  if (minutes === 0) {
    return `${hours} hr`;
  }
  return `${hours} hr ${minutes} min`;
}

export function parseSameHeader(rawHeader) {
  const normalized = rawHeader.trim();
  const match = normalized.match(ASCII_HEADER_RE);
  if (!match) {
    return null;
  }

  const [, originatorCode, eventCode, locationBlock, durationCode, issueCode, sender] = match;
  const locations = locationBlock.split("-").map(parseLocationCode).filter(Boolean);
  const durationMinutes = parseDurationCode(durationCode);
  const issued = parseIssueCode(issueCode);

  return {
    rawHeader: normalized,
    originatorCode,
    originatorLabel: ORIGINATORS[originatorCode] || "Unknown originator",
    eventCode,
    eventLabel: EVENTS[eventCode] || "Unknown event",
    durationCode,
    durationMinutes,
    durationText: formatDurationFromMinutes(durationMinutes),
    issueCode,
    issued,
    sender,
    locations,
  };
}

export function decodeSamePcm(samples, sampleRate, options = {}) {
  const resampled = resampleLinear(samples, sampleRate, TARGET_SAMPLE_RATE);
  const filtered = highPassBuffer(resampled);
  return decodeSameResampled(filtered, options);
}

export function decodeSameResampled(samples, options = {}) {
  const bursts = [];
  for (let phase = 0; phase < BIT_SAMPLES; phase += 1) {
    bursts.push(...scanPhase(samples, phase));
  }

  const dedupedBursts = dedupeBursts(bursts);
  const alerts = clusterAlerts(dedupedBursts, options.minRepeats ?? 1);
  return { alerts, bursts: dedupedBursts };
}

export class SAMEStreamDecoder {
  constructor(options = {}) {
    this.maxWindowSeconds = options.maxWindowSeconds ?? 90;
    this.minRepeats = options.minRepeats ?? MIN_STREAM_REPEAT_COUNT;
    this.sampleBuffer = new Float32Array(0);
    this.samplesSinceScan = 0;
    this.resampler = null;
    this.filter = new HighPassFilter();
    this.detectedAlerts = new Map();
  }

  reset() {
    this.sampleBuffer = new Float32Array(0);
    this.samplesSinceScan = 0;
    this.resampler = null;
    this.filter = new HighPassFilter();
    this.detectedAlerts.clear();
  }

  appendPcm(samples, inputSampleRate) {
    if (!this.resampler || this.resampler.inputRate !== inputSampleRate) {
      this.resampler = new LinearResampler(inputSampleRate, TARGET_SAMPLE_RATE);
      this.filter = new HighPassFilter();
    }

    const resampled = this.resampler.process(samples);
    if (!resampled.length) {
      return false;
    }

    const filtered = this.filter.process(resampled);
    this.sampleBuffer = appendFloat32(this.sampleBuffer, filtered);
    this.samplesSinceScan += filtered.length;

    const maxSamples = Math.floor(this.maxWindowSeconds * TARGET_SAMPLE_RATE);
    if (this.sampleBuffer.length > maxSamples) {
      this.sampleBuffer = this.sampleBuffer.slice(this.sampleBuffer.length - maxSamples);
    }

    return this.samplesSinceScan >= TARGET_SAMPLE_RATE;
  }

  scan() {
    this.samplesSinceScan = 0;
    const { alerts, bursts } = decodeSameResampled(this.sampleBuffer, { minRepeats: this.minRepeats });
    const now = new Date().toISOString();
    const merged = [];

    for (const alert of alerts) {
      const existing = this.detectedAlerts.get(alert.rawHeader);
      const stableAlert = existing
        ? {
            ...existing,
            confidence: Math.max(existing.confidence, alert.confidence),
            repeatCount: Math.max(existing.repeatCount, alert.repeatCount),
            lastSeen: now,
          }
        : {
            ...alert,
            firstSeen: now,
            lastSeen: now,
          };
      this.detectedAlerts.set(alert.rawHeader, stableAlert);
      merged.push(stableAlert);
    }

    merged.sort((left, right) => new Date(right.lastSeen).getTime() - new Date(left.lastSeen).getTime());
    return { alerts: merged, bursts };
  }
}

class LinearResampler {
  constructor(inputRate, outputRate) {
    this.inputRate = inputRate;
    this.outputRate = outputRate;
    this.step = inputRate / outputRate;
    this.position = 0;
    this.tailSample = null;
  }

  process(chunk) {
    if (!chunk || chunk.length === 0) {
      return new Float32Array(0);
    }

    let source;
    if (this.tailSample === null) {
      source = chunk;
    } else {
      source = new Float32Array(chunk.length + 1);
      source[0] = this.tailSample;
      source.set(chunk, 1);
    }

    const output = [];
    while (this.position + 1 < source.length) {
      const index = Math.floor(this.position);
      const fraction = this.position - index;
      const first = source[index];
      const second = source[index + 1];
      output.push(first + (second - first) * fraction);
      this.position += this.step;
    }

    this.position -= source.length - 1;
    this.tailSample = source[source.length - 1];
    return Float32Array.from(output);
  }
}

class HighPassFilter {
  constructor(alpha = 0.995) {
    this.alpha = alpha;
    this.lastInput = 0;
    this.lastOutput = 0;
  }

  process(chunk) {
    const output = new Float32Array(chunk.length);
    for (let index = 0; index < chunk.length; index += 1) {
      const input = chunk[index];
      const filtered = input - this.lastInput + this.alpha * this.lastOutput;
      output[index] = filtered;
      this.lastInput = input;
      this.lastOutput = filtered;
    }
    return output;
  }
}

function resampleLinear(samples, inputRate, outputRate) {
  if (inputRate === outputRate) {
    return samples.slice();
  }

  const outputLength = Math.max(0, Math.floor((samples.length * outputRate) / inputRate));
  const output = new Float32Array(outputLength);
  const ratio = inputRate / outputRate;

  for (let index = 0; index < outputLength; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const fraction = position - left;
    output[index] = samples[left] + (samples[right] - samples[left]) * fraction;
  }

  return output;
}

function highPassBuffer(samples) {
  const filter = new HighPassFilter();
  return filter.process(samples);
}

function scanPhase(samples, phase) {
  const available = samples.length - phase;
  if (available < BIT_SAMPLES * 24) {
    return [];
  }

  const bitCount = Math.floor(available / BIT_SAMPLES);
  const bits = new Uint8Array(bitCount);
  const bitConfidence = new Float32Array(bitCount);

  for (let bitIndex = 0; bitIndex < bitCount; bitIndex += 1) {
    const start = phase + bitIndex * BIT_SAMPLES;
    const { bit, confidence } = detectBit(samples, start);
    bits[bitIndex] = bit;
    bitConfidence[bitIndex] = confidence;
  }

  const bursts = [];
  for (let byteAlignment = 0; byteAlignment < 8; byteAlignment += 1) {
    const byteCount = Math.floor((bitCount - byteAlignment) / 8);
    if (byteCount <= PREAMBLE_RUN_BYTES + 4) {
      continue;
    }

    const bytes = new Uint8Array(byteCount);
    const byteConfidence = new Float32Array(byteCount);

    for (let byteIndex = 0; byteIndex < byteCount; byteIndex += 1) {
      let value = 0;
      let confidence = 0;
      for (let bitOffset = 0; bitOffset < 8; bitOffset += 1) {
        const absoluteBit = byteAlignment + byteIndex * 8 + bitOffset;
        value |= bits[absoluteBit] << bitOffset;
        confidence += bitConfidence[absoluteBit];
      }
      bytes[byteIndex] = value;
      byteConfidence[byteIndex] = confidence / 8;
    }

    for (let byteIndex = 0; byteIndex < byteCount - PREAMBLE_RUN_BYTES - 4; byteIndex += 1) {
      if (bytes[byteIndex] !== PREAMBLE_BYTE) {
        continue;
      }

      let runLength = 1;
      while (byteIndex + runLength < byteCount && bytes[byteIndex + runLength] === PREAMBLE_BYTE) {
        runLength += 1;
      }

      if (runLength < PREAMBLE_RUN_BYTES) {
        continue;
      }

      const payloadStart = byteIndex + runLength;
      const payload = readSameAscii(bytes, byteConfidence, payloadStart);
      if (!payload) {
        byteIndex += runLength - 1;
        continue;
      }

      bursts.push({
        kind: payload.text.startsWith("NNNN") ? "eom" : "header",
        rawText: payload.text,
        phase,
        startSample: phase + (byteAlignment + byteIndex * 8) * BIT_SAMPLES,
        endSample: phase + (byteAlignment + (payloadStart + payload.length) * 8) * BIT_SAMPLES,
        confidence: payload.confidence,
      });

      byteIndex += runLength - 1;
    }
  }

  return bursts;
}

function detectBit(samples, start) {
  let bit0Re = 0;
  let bit0Im = 0;
  let bit1Re = 0;
  let bit1Im = 0;
  let energy = 0;

  for (let index = 0; index < BIT_SAMPLES; index += 1) {
    const sample = samples[start + index];
    energy += sample * sample;
    bit0Re += sample * BIT0_COS[index];
    bit0Im -= sample * BIT0_SIN[index];
    bit1Re += sample * BIT1_COS[index];
    bit1Im -= sample * BIT1_SIN[index];
  }

  const bit0Energy = bit0Re * bit0Re + bit0Im * bit0Im;
  const bit1Energy = bit1Re * bit1Re + bit1Im * bit1Im;
  const totalToneEnergy = bit0Energy + bit1Energy;
  const confidence = totalToneEnergy > 0 ? Math.abs(bit1Energy - bit0Energy) / totalToneEnergy : 0;
  const gatedConfidence = energy > 1e-5 ? confidence : 0;

  return {
    bit: bit1Energy >= bit0Energy ? 1 : 0,
    confidence: gatedConfidence,
  };
}

function readSameAscii(bytes, byteConfidence, startIndex) {
  let text = "";
  let confidence = 0;
  let length = 0;

  for (let byteIndex = startIndex; byteIndex < bytes.length && length < MAX_HEADER_BYTES; byteIndex += 1) {
    const value = bytes[byteIndex] & 0x7f;
    if (!isHeaderByte(value)) {
      break;
    }

    const character = String.fromCharCode(value);
    text += character;
    confidence += byteConfidence[byteIndex];
    length += 1;

    if (text === "NNNN") {
      return {
        text,
        confidence: confidence / length,
        length,
      };
    }

    if (text.startsWith("ZCZC-") && SAME_CHAR_RE.test(text) && ASCII_HEADER_RE.test(text)) {
      return {
        text,
        confidence: confidence / length,
        length,
      };
    }
  }

  return null;
}

function isHeaderByte(value) {
  return (
    value === 32 ||
    value === 43 ||
    value === 45 ||
    value === 47 ||
    (value >= 48 && value <= 57) ||
    (value >= 65 && value <= 90)
  );
}

function dedupeBursts(bursts) {
  bursts.sort((left, right) => left.startSample - right.startSample || right.confidence - left.confidence);
  const unique = [];

  for (const burst of bursts) {
    const duplicate = unique.find(
      (candidate) =>
        candidate.rawText === burst.rawText &&
        Math.abs(candidate.startSample - burst.startSample) < TARGET_SAMPLE_RATE * 0.35,
    );

    if (!duplicate) {
      unique.push(burst);
      continue;
    }

    if (burst.confidence > duplicate.confidence) {
      duplicate.phase = burst.phase;
      duplicate.startSample = burst.startSample;
      duplicate.endSample = burst.endSample;
      duplicate.confidence = burst.confidence;
    }
  }

  return unique;
}

function clusterAlerts(bursts, minRepeats) {
  const headers = bursts.filter((burst) => burst.kind === "header").sort((left, right) => left.startSample - right.startSample);
  const groupedByHeader = new Map();

  for (const burst of headers) {
    const entries = groupedByHeader.get(burst.rawText) || [];
    entries.push(burst);
    groupedByHeader.set(burst.rawText, entries);
  }

  const alerts = [];
  for (const [rawHeader, entries] of groupedByHeader.entries()) {
    let cluster = [];

    for (const burst of entries) {
      if (cluster.length === 0) {
        cluster.push(burst);
        continue;
      }

      const previous = cluster[cluster.length - 1];
      if ((burst.startSample - previous.startSample) / TARGET_SAMPLE_RATE <= STREAM_GROUP_SECONDS) {
        cluster.push(burst);
      } else {
        finalizeCluster(rawHeader, cluster, alerts, minRepeats, bursts);
        cluster = [burst];
      }
    }

    finalizeCluster(rawHeader, cluster, alerts, minRepeats, bursts);
  }

  alerts.sort((left, right) => right.startSample - left.startSample);
  return alerts;
}

function finalizeCluster(rawHeader, cluster, alerts, minRepeats, bursts) {
  if (!cluster.length) {
    return;
  }

  const parsed = parseSameHeader(rawHeader);
  if (!parsed) {
    return;
  }

  const headerBursts = cluster.slice(0, HEADER_REPEAT_TARGET);
  const confidence =
    headerBursts.reduce((sum, burst) => sum + burst.confidence, 0) /
    Math.max(1, headerBursts.length);
  const repeatCount = headerBursts.length;

  if (repeatCount < minRepeats) {
    return;
  }

  const clusterStart = headerBursts[0].startSample;
  const clusterEnd = headerBursts[headerBursts.length - 1].endSample;
  const relatedBursts = bursts.filter(
    (burst) =>
      burst.startSample >= clusterStart - TARGET_SAMPLE_RATE * 0.5 &&
      burst.startSample <= clusterEnd + TARGET_SAMPLE_RATE * STREAM_GROUP_SECONDS * 2 &&
      ((burst.rawText === rawHeader && headerBursts.includes(burst)) || burst.kind === "eom"),
  );

  alerts.push({
    ...parsed,
    confidence,
    repeatCount,
    startSample: headerBursts[0].startSample,
    endSample: headerBursts[headerBursts.length - 1].endSample,
    rawBursts: relatedBursts.map((burst) => ({
      kind: burst.kind,
      rawText: burst.rawText,
      confidence: burst.confidence,
      startSample: burst.startSample,
      endSample: burst.endSample,
    })),
    id: hashHeader(rawHeader),
  });
}

function parseLocationCode(code) {
  if (!/^\d{6}$/.test(code)) {
    return null;
  }
  const partitionCode = code.slice(0, 1);
  const stateCode = code.slice(1, 3);
  const countyCode = code.slice(3);
  return {
    code,
    partitionCode,
    partitionLabel: PARTITIONS[partitionCode] || "Unknown area partition",
    stateCode,
    stateLabel: STATES[stateCode] || `State ${stateCode}`,
    countyCode,
  };
}

function parseDurationCode(code) {
  if (!/^\d{4}$/.test(code)) {
    return Number.NaN;
  }
  const hours = Number(code.slice(0, 2));
  const minutes = Number(code.slice(2, 4));
  return hours * 60 + minutes;
}

function parseIssueCode(code) {
  if (!/^\d{7}$/.test(code)) {
    return null;
  }

  const now = new Date();
  const year = now.getUTCFullYear();
  const dayOfYear = Number(code.slice(0, 3));
  const hour = Number(code.slice(3, 5));
  const minute = Number(code.slice(5, 7));

  const utcDate = new Date(Date.UTC(year, 0, 1, hour, minute));
  utcDate.setUTCDate(dayOfYear);

  if (utcDate.getTime() - now.getTime() > 36 * 60 * 60 * 1000) {
    utcDate.setUTCFullYear(year - 1);
    utcDate.setUTCDate(dayOfYear);
  }

  return {
    dayOfYear,
    hour,
    minute,
    iso: utcDate.toISOString(),
    display: utcDate.toLocaleString(),
  };
}

function hashHeader(value) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `same-${(hash >>> 0).toString(16)}`;
}
