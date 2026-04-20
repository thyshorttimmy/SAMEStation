from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Any

import json

import numpy as np
from same_paths import resource_root


TARGET_SAMPLE_RATE = 12_500
BIT_SAMPLES = 24
BIT_RATE = TARGET_SAMPLE_RATE / BIT_SAMPLES
BIT0_FREQ = 1562.5
BIT1_FREQ = 2083.3333333333335
PREAMBLE_BYTE = 0xAB
PREAMBLE_RUN_BYTES = 8
MAX_HEADER_BYTES = 280
MIN_STREAM_REPEAT_COUNT = 2
STREAM_GROUP_SECONDS = 6
HEADER_REPEAT_TARGET = 3

ASCII_HEADER_RE = re.compile(
    r"^ZCZC-([A-Z0-9]{3})-([A-Z0-9]{3})-([0-9]{6}(?:-[0-9]{6})*)\+([0-9]{4})-([0-9]{7})-([A-Z0-9/ ]{1,16})-$"
)
SAME_CHAR_RE = re.compile(r"^[ A-Z0-9/+-]+$")

ORIGINATORS = {
    "CIV": "Civil authorities",
    "EAS": "Broadcast station or cable system",
    "PEP": "Primary Entry Point system",
    "WXR": "National Weather Service",
}

PARTITIONS = {
    "0": "Entire area",
    "1": "Northwest",
    "2": "North",
    "3": "Northeast",
    "4": "West",
    "5": "Central",
    "6": "East",
    "7": "Southwest",
    "8": "South",
    "9": "Southeast",
}

STATES = {
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
}

EVENTS = {
    "ADR": "Administrative message",
    "AVA": "Avalanche watch",
    "AVW": "Avalanche warning",
    "BHW": "Biological hazard warning",
    "BLU": "Blue alert",
    "BZW": "Blizzard warning",
    "CAE": "Child abduction emergency",
    "CDW": "Civil danger warning",
    "CEM": "Civil emergency message",
    "DMO": "Demo message",
    "DSW": "Dust storm warning",
    "EAN": "Emergency action notification",
    "EAT": "Emergency action termination",
    "EQW": "Earthquake warning",
    "EVI": "Evacuation immediate",
    "FFA": "Flash flood watch",
    "FFW": "Flash flood warning",
    "FLS": "Flood statement",
    "FLA": "Flood watch",
    "FLW": "Flood warning",
    "FRW": "Fire warning",
    "FZW": "Freeze warning",
    "HLS": "Hurricane local statement",
    "HUA": "Hurricane watch",
    "HUW": "Hurricane warning",
    "LAE": "Local area emergency",
    "LEW": "Law enforcement warning",
    "NIC": "National information center",
    "NMN": "Network message notification",
    "NPT": "National periodic test",
    "NUW": "Nuclear power plant warning",
    "RMT": "Required monthly test",
    "RWT": "Required weekly test",
    "SMW": "Special marine warning",
    "SPS": "Special weather statement",
    "SPW": "Shelter in place warning",
    "SQW": "Snow squall warning",
    "SSA": "Storm surge watch",
    "SSW": "Storm surge warning",
    "SVA": "Severe thunderstorm watch",
    "SVR": "Severe thunderstorm warning",
    "TOA": "Tornado watch",
    "TOR": "Tornado warning",
    "TSA": "Tsunami watch",
    "TSW": "Tsunami warning",
    "VOW": "Volcano warning",
    "WSW": "Winter storm warning",
}

ROOT_DIR = resource_root()
SAME_CODES_PATH = ROOT_DIR / "data" / "same_codes.json"
if SAME_CODES_PATH.exists():
    SAME_CODE_MAP = json.loads(SAME_CODES_PATH.read_text(encoding="utf-8"))
else:
    SAME_CODE_MAP = {}

BIT0_COS = np.cos((2 * np.pi * 3 * np.arange(BIT_SAMPLES)) / BIT_SAMPLES).astype(np.float32)
BIT0_SIN = np.sin((2 * np.pi * 3 * np.arange(BIT_SAMPLES)) / BIT_SAMPLES).astype(np.float32)
BIT1_COS = np.cos((2 * np.pi * 4 * np.arange(BIT_SAMPLES)) / BIT_SAMPLES).astype(np.float32)
BIT1_SIN = np.sin((2 * np.pi * 4 * np.arange(BIT_SAMPLES)) / BIT_SAMPLES).astype(np.float32)
BIT_WEIGHTS = (1 << np.arange(8, dtype=np.uint8)).astype(np.uint16)


def format_duration_from_minutes(total_minutes: int | float) -> str:
    if not math.isfinite(total_minutes):
        return "Unknown"
    total_minutes = int(total_minutes)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours == 0:
        return f"{minutes} min"
    if minutes == 0:
        return f"{hours} hr"
    return f"{hours} hr {minutes} min"


def parse_same_header(raw_header: str) -> dict[str, Any] | None:
    normalized = raw_header.strip()
    match = ASCII_HEADER_RE.match(normalized)
    if not match:
        return None

    originator_code, event_code, location_block, duration_code, issue_code, sender = match.groups()
    locations = [parsed for code in location_block.split("-") if (parsed := parse_location_code(code))]
    duration_minutes = parse_duration_code(duration_code)
    issued = parse_issue_code(issue_code)

    return {
        "rawHeader": normalized,
        "originatorCode": originator_code,
        "originatorLabel": ORIGINATORS.get(originator_code, "Unknown originator"),
        "eventCode": event_code,
        "eventLabel": EVENTS.get(event_code, "Unknown event"),
        "durationCode": duration_code,
        "durationMinutes": duration_minutes,
        "durationText": format_duration_from_minutes(duration_minutes),
        "issueCode": issue_code,
        "issued": issued,
        "sender": sender,
        "locations": locations,
    }


def decode_same_pcm(samples: np.ndarray, sample_rate: int | float, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    resampled = resample_linear(np.asarray(samples, dtype=np.float32), float(sample_rate), TARGET_SAMPLE_RATE)
    filtered = high_pass_buffer(resampled)
    return decode_same_resampled(filtered, options)


def decode_same_resampled(samples: np.ndarray, options: dict[str, Any] | None = None) -> dict[str, Any]:
    options = options or {}
    sample_offset = int(options.get("sampleOffset", 0))
    bursts: list[dict[str, Any]] = []
    for phase in range(BIT_SAMPLES):
        bursts.extend(scan_phase(samples, phase, sample_offset))
    deduped_bursts = dedupe_bursts(bursts)
    alerts = cluster_alerts(deduped_bursts, int(options.get("minRepeats", 1)))
    return {"alerts": alerts, "bursts": deduped_bursts}


class LinearResampler:
    def __init__(self, input_rate: int | float, output_rate: int | float) -> None:
        self.input_rate = float(input_rate)
        self.output_rate = float(output_rate)
        self.step = self.input_rate / self.output_rate
        self.position = 0.0
        self.tail_sample: float | None = None

    def process(self, chunk: np.ndarray) -> np.ndarray:
        if chunk.size == 0:
            return np.zeros(0, dtype=np.float32)

        chunk = np.asarray(chunk, dtype=np.float32)
        if self.tail_sample is None:
            source = chunk
        else:
            source = np.concatenate((np.asarray([self.tail_sample], dtype=np.float32), chunk))

        output: list[float] = []
        while self.position + 1 < source.size:
            index = int(self.position)
            fraction = self.position - index
            first = float(source[index])
            second = float(source[index + 1])
            output.append(first + (second - first) * fraction)
            self.position += self.step

        self.position -= max(0, source.size - 1)
        self.tail_sample = float(source[-1])
        return np.asarray(output, dtype=np.float32)


class HighPassFilter:
    def __init__(self, alpha: float = 0.995) -> None:
        self.alpha = alpha
        self.last_input = 0.0
        self.last_output = 0.0

    def process(self, chunk: np.ndarray) -> np.ndarray:
        chunk = np.asarray(chunk, dtype=np.float32)
        output = np.empty_like(chunk)
        for index, value in enumerate(chunk):
            filtered = float(value) - self.last_input + self.alpha * self.last_output
            output[index] = filtered
            self.last_input = float(value)
            self.last_output = filtered
        return output


class SAMEStreamDecoder:
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        options = options or {}
        self.max_window_seconds = int(options.get("maxWindowSeconds", 30))
        self.min_repeats = int(options.get("minRepeats", MIN_STREAM_REPEAT_COUNT))
        self.sample_buffer = np.zeros(0, dtype=np.float32)
        self.samples_since_scan = 0
        self.buffer_start_sample = 0
        self.resampler: LinearResampler | None = None
        self.filter = HighPassFilter()
        self.seen_burst_keys: set[tuple[str, str, int]] = set()

    def reset(self) -> None:
        self.sample_buffer = np.zeros(0, dtype=np.float32)
        self.samples_since_scan = 0
        self.buffer_start_sample = 0
        self.resampler = None
        self.filter = HighPassFilter()
        self.seen_burst_keys.clear()

    def append_pcm(self, samples: np.ndarray, input_sample_rate: int | float) -> bool:
        if self.resampler is None or self.resampler.input_rate != float(input_sample_rate):
            self.resampler = LinearResampler(input_sample_rate, TARGET_SAMPLE_RATE)
            self.filter = HighPassFilter()

        resampled = self.resampler.process(np.asarray(samples, dtype=np.float32))
        if resampled.size == 0:
            return False

        filtered = self.filter.process(resampled)
        if self.sample_buffer.size == 0:
            self.sample_buffer = filtered
        else:
            self.sample_buffer = np.concatenate((self.sample_buffer, filtered))
        self.samples_since_scan += int(filtered.size)

        max_samples = int(self.max_window_seconds * TARGET_SAMPLE_RATE)
        if self.sample_buffer.size > max_samples:
            excess = int(self.sample_buffer.size - max_samples)
            self.sample_buffer = self.sample_buffer[excess:]
            self.buffer_start_sample += excess
            self._prune_seen_bursts()

        return self.samples_since_scan >= TARGET_SAMPLE_RATE

    def scan(self) -> dict[str, Any]:
        self.samples_since_scan = 0
        result = decode_same_resampled(
            self.sample_buffer,
            {"minRepeats": self.min_repeats, "sampleOffset": self.buffer_start_sample},
        )

        new_bursts: list[dict[str, Any]] = []
        for burst in result["bursts"]:
            key = (burst["kind"], burst["rawText"], int(burst["startSample"]))
            if key in self.seen_burst_keys:
                continue
            self.seen_burst_keys.add(key)
            new_bursts.append(burst)

        return {
            "alerts": result["alerts"],
            "bursts": result["bursts"],
            "newBursts": new_bursts,
        }

    def _prune_seen_bursts(self) -> None:
        minimum_start = self.buffer_start_sample - (TARGET_SAMPLE_RATE * 5)
        self.seen_burst_keys = {
            key for key in self.seen_burst_keys if key[2] >= minimum_start
        }


def resample_linear(samples: np.ndarray, input_rate: float, output_rate: float) -> np.ndarray:
    if samples.size == 0:
        return np.zeros(0, dtype=np.float32)
    if input_rate == output_rate:
        return samples.astype(np.float32, copy=True)

    output_length = max(0, int(math.floor((samples.size * output_rate) / input_rate)))
    if output_length == 0:
        return np.zeros(0, dtype=np.float32)

    source_positions = np.arange(samples.size, dtype=np.float32)
    target_positions = np.arange(output_length, dtype=np.float32) * (input_rate / output_rate)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


def high_pass_buffer(samples: np.ndarray) -> np.ndarray:
    return HighPassFilter().process(samples)


def scan_phase(samples: np.ndarray, phase: int, sample_offset: int = 0) -> list[dict[str, Any]]:
    available = int(samples.size - phase)
    if available < BIT_SAMPLES * 24:
        return []

    bit_count = available // BIT_SAMPLES
    trimmed = samples[phase : phase + bit_count * BIT_SAMPLES].reshape(bit_count, BIT_SAMPLES)

    bit0_re = trimmed @ BIT0_COS
    bit0_im = -(trimmed @ BIT0_SIN)
    bit1_re = trimmed @ BIT1_COS
    bit1_im = -(trimmed @ BIT1_SIN)
    energy = np.sum(trimmed * trimmed, axis=1)

    bit0_energy = bit0_re * bit0_re + bit0_im * bit0_im
    bit1_energy = bit1_re * bit1_re + bit1_im * bit1_im
    total_tone_energy = bit0_energy + bit1_energy

    confidence = np.zeros(bit_count, dtype=np.float32)
    valid = total_tone_energy > 0
    confidence[valid] = np.abs(bit1_energy[valid] - bit0_energy[valid]) / total_tone_energy[valid]
    confidence[energy <= 1e-5] = 0

    bits = (bit1_energy >= bit0_energy).astype(np.uint8)

    bursts: list[dict[str, Any]] = []

    for bit_offset in range(8):
        shifted_bit_count = (bit_count - bit_offset) // 8
        if shifted_bit_count <= 0:
            continue

        shifted_bits = bits[bit_offset : bit_offset + shifted_bit_count * 8]
        shifted_confidence = confidence[bit_offset : bit_offset + shifted_bit_count * 8]
        bit_matrix = shifted_bits.reshape(shifted_bit_count, 8)
        confidence_matrix = shifted_confidence.reshape(shifted_bit_count, 8)
        bytes_view = np.sum(bit_matrix.astype(np.uint16) * BIT_WEIGHTS, axis=1).astype(np.uint8)
        byte_confidence = np.mean(confidence_matrix, axis=1)

        byte_index = 0
        upper_bound = shifted_bit_count - PREAMBLE_RUN_BYTES - 4
        while byte_index < upper_bound:
            if int(bytes_view[byte_index]) != PREAMBLE_BYTE:
                byte_index += 1
                continue

            run_length = 1
            while byte_index + run_length < shifted_bit_count and int(bytes_view[byte_index + run_length]) == PREAMBLE_BYTE:
                run_length += 1

            if run_length < PREAMBLE_RUN_BYTES:
                byte_index += 1
                continue

            payload_start = byte_index + run_length
            payload = read_same_ascii(bytes_view, byte_confidence, payload_start)
            if payload is None:
                byte_index += run_length
                continue

            bursts.append(
                {
                    "kind": "eom" if payload["text"].startswith("NNNN") else "header",
                    "rawText": payload["text"],
                    "phase": phase,
                    "startSample": sample_offset + phase + (bit_offset + byte_index * 8) * BIT_SAMPLES,
                    "endSample": sample_offset + phase + (bit_offset + (payload_start + payload["length"]) * 8) * BIT_SAMPLES,
                    "confidence": payload["confidence"],
                }
            )
            byte_index += run_length

    return bursts


def read_same_ascii(bytes_view: np.ndarray, byte_confidence: np.ndarray, start_index: int) -> dict[str, Any] | None:
    text_parts: list[str] = []
    confidence_sum = 0.0
    length = 0

    for byte_index in range(start_index, min(bytes_view.size, start_index + MAX_HEADER_BYTES)):
        value = int(bytes_view[byte_index] & 0x7F)
        if not is_header_byte(value):
            break

        character = chr(value)
        text_parts.append(character)
        confidence_sum += float(byte_confidence[byte_index])
        length += 1
        text = "".join(text_parts)

        if text == "NNNN":
            return {"text": text, "confidence": confidence_sum / length, "length": length}

        if text.startswith("ZCZC-") and SAME_CHAR_RE.match(text) and ASCII_HEADER_RE.match(text):
            return {"text": text, "confidence": confidence_sum / length, "length": length}

    return None


def is_header_byte(value: int) -> bool:
    return value in {32, 43, 45, 47} or 48 <= value <= 57 or 65 <= value <= 90


def dedupe_bursts(bursts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bursts = sorted(bursts, key=lambda burst: (burst["startSample"], -burst["confidence"]))
    unique: list[dict[str, Any]] = []

    for burst in bursts:
        duplicate = next(
            (
                candidate
                for candidate in unique
                if candidate["rawText"] == burst["rawText"]
                and abs(candidate["startSample"] - burst["startSample"]) < TARGET_SAMPLE_RATE * 0.35
            ),
            None,
        )
        if duplicate is None:
            unique.append(dict(burst))
            continue
        if burst["confidence"] > duplicate["confidence"]:
            duplicate.update(burst)

    return unique


def cluster_alerts(bursts: list[dict[str, Any]], min_repeats: int) -> list[dict[str, Any]]:
    headers = sorted((burst for burst in bursts if burst["kind"] == "header"), key=lambda burst: burst["startSample"])
    grouped_by_header: dict[str, list[dict[str, Any]]] = {}
    for burst in headers:
        grouped_by_header.setdefault(burst["rawText"], []).append(burst)

    alerts: list[dict[str, Any]] = []
    for raw_header, entries in grouped_by_header.items():
        cluster: list[dict[str, Any]] = []
        for burst in entries:
            if not cluster:
                cluster.append(burst)
                continue

            previous = cluster[-1]
            if (burst["startSample"] - previous["startSample"]) / TARGET_SAMPLE_RATE <= STREAM_GROUP_SECONDS:
                cluster.append(burst)
            else:
                finalize_cluster(raw_header, cluster, alerts, min_repeats, bursts)
                cluster = [burst]
        finalize_cluster(raw_header, cluster, alerts, min_repeats, bursts)

    alerts.sort(key=lambda alert: alert["startSample"], reverse=True)
    return alerts


def finalize_cluster(
    raw_header: str,
    cluster: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    min_repeats: int,
    bursts: list[dict[str, Any]],
) -> None:
    if not cluster:
        return

    parsed = parse_same_header(raw_header)
    if parsed is None:
        return

    header_bursts = cluster[:HEADER_REPEAT_TARGET]
    repeat_count = len(header_bursts)
    if repeat_count < min_repeats:
        return

    confidence = sum(float(burst["confidence"]) for burst in header_bursts) / max(1, repeat_count)
    cluster_start = header_bursts[0]["startSample"]
    cluster_end = header_bursts[-1]["endSample"]
    related_bursts = [
        burst
        for burst in bursts
        if burst["startSample"] >= cluster_start - int(TARGET_SAMPLE_RATE * 0.5)
        and burst["startSample"] <= cluster_end + int(TARGET_SAMPLE_RATE * STREAM_GROUP_SECONDS * 2)
        and ((burst["rawText"] == raw_header and burst in header_bursts) or burst["kind"] == "eom")
    ]

    alerts.append(
        {
            **parsed,
            "confidence": confidence,
            "repeatCount": repeat_count,
            "startSample": header_bursts[0]["startSample"],
            "endSample": header_bursts[-1]["endSample"],
            "rawBursts": [
                {
                    "kind": burst["kind"],
                    "rawText": burst["rawText"],
                    "confidence": float(burst["confidence"]),
                    "startSample": int(burst["startSample"]),
                    "endSample": int(burst["endSample"]),
                }
                for burst in related_bursts
            ],
            "id": hash_header(raw_header),
        }
    )


def parse_location_code(code: str) -> dict[str, Any] | None:
    if not re.match(r"^\d{6}$", code):
        return None
    partition_code = code[:1]
    state_code = code[1:3]
    county_code = code[3:]
    same_entry = SAME_CODE_MAP.get(code)
    county_name = same_entry.get("countyName") if same_entry else None
    state_abbr = same_entry.get("stateAbbr") if same_entry else None
    return {
        "code": code,
        "partitionCode": partition_code,
        "partitionLabel": PARTITIONS.get(partition_code, "Unknown area partition"),
        "stateCode": state_code,
        "stateLabel": STATES.get(state_code, f"State {state_code}"),
        "stateAbbr": state_abbr,
        "countyCode": county_code,
        "countyName": county_name,
        "locationLabel": (
            f"{county_name}, {state_abbr or STATES.get(state_code, f'State {state_code}')}"
            if county_name
            else None
        ),
    }


def parse_duration_code(code: str) -> int | float:
    if not re.match(r"^\d{4}$", code):
        return float("nan")
    hours = int(code[:2])
    minutes = int(code[2:])
    return hours * 60 + minutes


def parse_issue_code(code: str) -> dict[str, Any] | None:
    if not re.match(r"^\d{7}$", code):
        return None

    now = datetime.now(timezone.utc)
    year = now.year
    day_of_year = int(code[:3])
    hour = int(code[3:5])
    minute = int(code[5:7])

    utc_date = datetime(year, 1, 1, hour, minute, tzinfo=timezone.utc) + timedelta(days=day_of_year - 1)
    if (utc_date - now) > timedelta(hours=36):
        utc_date = utc_date.replace(year=year - 1)

    local_time = utc_date.astimezone()
    return {
        "dayOfYear": day_of_year,
        "hour": hour,
        "minute": minute,
        "iso": utc_date.isoformat().replace("+00:00", "Z"),
        "display": local_time.strftime("%m/%d/%Y, %I:%M:%S %p").lstrip("0").replace(" 0", " "),
        "pubDate": format_datetime(utc_date),
    }


def hash_header(value: str) -> str:
    hash_value = 2166136261
    for char in value:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return f"same-{hash_value:08x}"
