#!/usr/bin/env python3
"""Verify RECX waveform structure and exact subtitle mapping without rewriting files."""

from __future__ import annotations

import argparse
import base64
import math
import struct
import sys
from pathlib import Path
from xml.etree import ElementTree

import generate_recx as generator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify RECX files next to MP3 files.")
    parser.add_argument("folder", type=Path, help="Folder containing MP3, RECX, and subtitle files.")
    parser.add_argument(
        "--subtitle-suffix",
        default="",
        help="Subtitle suffix used to build RECX tags, for example _zh.",
    )
    parser.add_argument("--ffprobe", default="ffprobe", help="ffprobe executable for waveform duration checks.")
    parser.add_argument("--ffmpeg", default="ffmpeg", help="ffmpeg executable for deterministic waveform checks.")
    parser.add_argument("--skip-wave-duration", action="store_true", help="Skip audio-duration checks.")
    return parser.parse_args()


def expected_cues(audio: Path, suffix: str) -> list[tuple[float, float, str]]:
    subtitle = generator.subtitle_path(audio, None, True, suffix)
    if subtitle is None:
        raise ValueError(f"missing subtitle with suffix {suffix!r}")
    if subtitle.suffix.lower() == ".lrc":
        return generator.parse_lrc(generator.read_text(subtitle), generator.probe_duration(audio, "ffprobe"))
    return generator.parse_srt_or_vtt(generator.read_text(subtitle))


def parse_recx(path: Path) -> tuple[list[tuple[float, float]], list[tuple[float, float, str]], float]:
    root = ElementTree.parse(path).getroot()
    if root.tag != "media":
        raise ValueError(f"root is {root.tag!r}, not 'media'")
    wave = root.find("wave")
    if wave is None or wave.get("bits") != "64" or not wave.get("data"):
        raise ValueError("missing 64-bit wave data")
    try:
        encoded = base64.b64decode(wave.attrib["data"], validate=True)
    except ValueError as exc:
        raise ValueError(f"invalid wave base64: {exc}") from exc
    if not encoded or len(encoded) % 16:
        raise ValueError("wave payload is not a non-empty Float64 pair sequence")
    points = [(time_value / 100.0, amplitude) for time_value, amplitude in struct.iter_unpack("<dd", encoded)]
    if points[-1] != (0.0, 0.0):
        raise ValueError("wave payload does not end with the legacy zero sentinel")
    wave_points = points[:-1]
    if not wave_points or wave_points[0] != (0.0, 0.0):
        raise ValueError("wave payload does not begin with the legacy zero point")
    previous = -1.0
    for time_value, amplitude in wave_points:
        if not math.isfinite(time_value) or not math.isfinite(amplitude):
            raise ValueError("wave contains a non-finite number")
        if time_value < previous or amplitude < 0 or amplitude > 1:
            raise ValueError("wave time or amplitude is outside the supported range")
        previous = time_value
    tags: list[tuple[float, float, str]] = []
    for tag in root.findall("tag"):
        try:
            text = base64.b64decode(tag.attrib["text"], validate=True).decode("utf-8")
            tags.append((float(tag.attrib["time1"]), float(tag.attrib["time2"]), text))
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise ValueError(f"invalid subtitle tag: {exc}") from exc
    return wave_points, tags, wave_points[-1][0]


def validate_file(audio: Path, subtitle_suffix: str, ffprobe: str, ffmpeg: str, check_duration: bool) -> list[str]:
    recx = audio.with_suffix(".recx")
    errors: list[str] = []
    if not recx.is_file():
        return ["missing RECX"]
    try:
        wave_points, actual_cues, last_time = parse_recx(recx)
        source_cues = expected_cues(audio, subtitle_suffix)
    except (ElementTree.ParseError, OSError, ValueError) as exc:
        return [str(exc)]
    try:
        magnitudes = generator.decode_peak_magnitudes(audio, ffmpeg)
        expected_points, _ = generator.wave_points(magnitudes, 0.995, 0.55)
    except (OSError, RuntimeError) as exc:
        return [f"cannot regenerate waveform: {exc}"]
    if len(wave_points) != len(expected_points):
        errors.append(f"wave point count {len(wave_points)} != {len(expected_points)}")
    else:
        for index, (actual, expected) in enumerate(zip(wave_points, expected_points), start=1):
            if not math.isclose(actual[0], expected[0], rel_tol=0.0, abs_tol=1e-12) or not math.isclose(actual[1], expected[1], rel_tol=0.0, abs_tol=1e-12):
                errors.append(f"wave point {index} differs from deterministic audio regeneration")
                break
    if len(actual_cues) != len(source_cues):
        errors.append(f"subtitle count {len(actual_cues)} != {len(source_cues)}")
    for index, (actual, source) in enumerate(zip(actual_cues, source_cues), start=1):
        source_start, source_end, source_text = source
        actual_start, actual_end, actual_text = actual
        if round(actual_start, 2) != round(source_start, 2) or round(actual_end, 2) != round(max(source_end, source_start + 0.01), 2):
            errors.append(f"subtitle {index} timing differs from source")
            break
        if actual_text != source_text:
            errors.append(f"subtitle {index} text differs from source")
            break
    if check_duration:
        duration = generator.probe_duration(audio, ffprobe)
        if duration is None:
            errors.append("ffprobe could not read audio duration")
        elif abs(last_time - duration) > 0.35:
            errors.append(f"wave end {last_time:.2f}s is inconsistent with audio duration {duration:.2f}s")
    if len(wave_points) < 2:
        errors.append("wave has fewer than two points")
    return errors


def main() -> int:
    args = parse_args()
    folder = args.folder.expanduser().resolve()
    audio = sorted(folder.glob("*.mp3"), key=lambda item: item.name.lower())
    if not audio:
        print(f"No MP3 files found: {folder}", file=sys.stderr)
        return 2
    failed = 0
    for item in audio:
        errors = validate_file(item, args.subtitle_suffix, args.ffprobe, args.ffmpeg, not args.skip_wave_duration)
        if errors:
            failed += 1
            print(f"FAIL {item.name}: {'; '.join(errors)}")
    print(f"Checked {len(audio)} MP3/RECX pairs; errors={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
