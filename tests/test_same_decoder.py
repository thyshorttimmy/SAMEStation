from __future__ import annotations

import math
import unittest

import numpy as np

from same_decoder import decode_same_pcm, parse_same_header


BIT_DURATION_SECONDS = 1 / 520.8333333333334
SPACE_FREQUENCY = 1562.5
MARK_FREQUENCY = 2083.3333333333335


class SameDecoderTests(unittest.TestCase):
    def test_parse_same_header_extracts_fields(self) -> None:
        parsed = parse_same_header("ZCZC-WXR-TOR-048439+0030-1091415-KDDC/NWS-")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["originatorCode"], "WXR")
        self.assertEqual(parsed["eventCode"], "TOR")
        self.assertEqual(parsed["durationMinutes"], 30)
        self.assertEqual(parsed["locations"][0]["stateCode"], "48")
        self.assertEqual(parsed["locations"][0]["countyCode"], "439")

    def test_decode_same_pcm_recovers_header_and_eom(self) -> None:
        header = "ZCZC-WXR-SVR-020013-020027+0045-1091415-KCLE/NWS-"
        samples = generate_alert_with_eom(header, sample_rate=48_000)
        result = decode_same_pcm(samples, 48_000, {"minRepeats": 2})

        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["rawHeader"], header)
        self.assertGreater(result["alerts"][0]["confidence"], 0.4)
        self.assertEqual(result["alerts"][0]["repeatCount"], 3)
        self.assertTrue(any(burst["kind"] == "eom" for burst in result["bursts"]))

    def test_decode_same_pcm_ignores_fourth_identical_header_repeat(self) -> None:
        header = "ZCZC-WXR-SVR-020013-020027+0045-1091415-KCLE/NWS-"
        samples = generate_alert_with_eom(header, sample_rate=48_000, header_repeats=4)
        result = decode_same_pcm(samples, 48_000, {"minRepeats": 2})

        self.assertEqual(len(result["alerts"]), 1)
        self.assertEqual(result["alerts"][0]["repeatCount"], 3)
        self.assertEqual(
            len([burst for burst in result["alerts"][0]["rawBursts"] if burst["kind"] == "header"]),
            3,
        )


def generate_alert_with_eom(header: str, sample_rate: int = 48_000, header_repeats: int = 3) -> np.ndarray:
    sequence: list[float] = []
    sequence.extend(render_silence(sample_rate, 0.3))
    for repeat in range(header_repeats):
        if repeat:
            sequence.extend(render_silence(sample_rate, 1.0))
        sequence.extend(render_burst(header, sample_rate, phase_offset=0.51))
    sequence.extend(render_silence(sample_rate, 2.0))
    for repeat in range(3):
        if repeat:
            sequence.extend(render_silence(sample_rate, 1.0))
        sequence.extend(render_burst("NNNN", sample_rate, phase_offset=0.12))
    sequence.extend(render_silence(sample_rate, 0.3))

    random = seeded_random(0x8A11)
    output = np.zeros(len(sequence), dtype=np.float32)
    for index, value in enumerate(sequence):
        output[index] = value + ((random() * 2) - 1) * 0.01
    return output


def render_burst(text: str, sample_rate: int, phase_offset: float) -> list[float]:
    bytes_out = [0xAB] * 16
    bytes_out.extend(ord(character) for character in text)
    bits: list[int] = []
    for value in bytes_out:
        for bit in range(8):
            bits.append((value >> bit) & 1)

    samples_per_bit = BIT_DURATION_SECONDS * sample_rate
    total_samples = math.ceil(len(bits) * samples_per_bit)
    signal = np.zeros(total_samples, dtype=np.float32)
    for sample_index in range(total_samples):
        time_seconds = sample_index / sample_rate
        bit_index = min(len(bits) - 1, int(time_seconds / BIT_DURATION_SECONDS))
        frequency = MARK_FREQUENCY if bits[bit_index] else SPACE_FREQUENCY
        signal[sample_index] = 0.7 * math.sin((2 * math.pi * frequency * time_seconds) + phase_offset)
    return signal.tolist()


def render_silence(sample_rate: int, seconds: float) -> list[float]:
    return np.zeros(math.ceil(sample_rate * seconds), dtype=np.float32).tolist()


def seeded_random(seed: int):
    state = seed & 0xFFFFFFFF

    def next_random() -> float:
        nonlocal state
        state = (1664525 * state + 1013904223) & 0xFFFFFFFF
        return state / 0x100000000

    return next_random


if __name__ == "__main__":
    unittest.main()
