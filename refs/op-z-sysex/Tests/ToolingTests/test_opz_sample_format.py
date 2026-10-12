import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from opz_sample_format import (  # noqa: E402
    DRUM_MAX_FRAMES,
    SAMPLE_RATE,
    create_drum_sample,
    create_synth_sample,
    read_aiff_pcm,
    read_op1_metadata,
)


def write_wave(path: Path, frames: int, value: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(value.to_bytes(2, "little", signed=True) * frames)


class SampleFormatTests(unittest.TestCase):
    def test_synth_sample_has_audio_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "tone.wav"
            output = root / "tone.aif"
            write_wave(source, SAMPLE_RATE, 1000)
            report = create_synth_sample(source, output, "Tone", 220)
            audio, frames = read_aiff_pcm(output)
            metadata = read_op1_metadata(output)
            self.assertEqual(frames, SAMPLE_RATE)
            self.assertEqual(len(audio), SAMPLE_RATE * 2)
            self.assertEqual(metadata["type"], "sampler")
            self.assertEqual(metadata["base_freq"], 220)
            self.assertFalse(report["trimmed"])

    def test_drum_pack_preserves_order_and_fits_twelve_seconds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.wav"
            second = root / "second.wav"
            output = root / "kit.aif"
            write_wave(first, SAMPLE_RATE * 8, 1000)
            write_wave(second, SAMPLE_RATE * 8, 2000)
            report = create_drum_sample(
                [(first, None, 0), (second, None, -6)], output, "Kit"
            )
            metadata = read_op1_metadata(output)
            _, frames = read_aiff_pcm(output)
            self.assertEqual(frames, SAMPLE_RATE * 8)
            self.assertLessEqual(frames, DRUM_MAX_FRAMES)
            self.assertEqual(report["slices"][0]["source"], str(first))
            self.assertEqual(report["slices"][1]["source"], str(second))
            self.assertEqual(metadata["type"], "drum")
            self.assertEqual(len(metadata["start"]), 24)
            self.assertEqual(metadata["start"][1], metadata["end"][0])
            self.assertLess(metadata["volume"][1], metadata["volume"][0])

    def test_over_budget_equal_hits_share_tail_reduction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = []
            for index in range(4):
                source = root / f"{index}.wav"
                write_wave(source, SAMPLE_RATE * 4, 1000 + index)
                sources.append((source, None, 0))
            report = create_drum_sample(sources, root / "kit.aif", "Even")
            self.assertEqual(report["total_frames"], DRUM_MAX_FRAMES)
            self.assertEqual(
                [item["used_frames"] for item in report["slices"]],
                [SAMPLE_RATE * 3] * 4,
            )


if __name__ == "__main__":
    unittest.main()
