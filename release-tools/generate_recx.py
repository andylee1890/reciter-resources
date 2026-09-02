#!/usr/bin/env python3
"""Generate EasyTyeReciter-compatible .recx waveform sidecars.

The generated XML is intentionally compatible with the legacy .rec format.
It contains only reusable media metadata: a waveform and optional subtitles;
it never stores an individual learner's playback or review state.
"""

from __future__ import annotations

import argparse
import audioop
import base64
import math
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


SAMPLE_RATE = 44_100
CHANNELS = 2
WINDOW_SECONDS = 0.1
WINDOW_FRAMES = int(SAMPLE_RATE * WINDOW_SECONDS)
WINDOW_BYTES = WINDOW_FRAMES * CHANNELS * 2  # signed 16-bit PCM
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus", ".wma", ".aiff", ".aif"}
SUBTITLE_EXTENSIONS = (".srt", ".vtt", ".lrc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create legacy-compatible .recx waveform files next to audio files."
    )
    parser.add_argument("input", type=Path, help="One audio file or a folder containing audio files.")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing .recx file.")
    parser.add_argument("--dry-run", action="store_true", help="Report planned outputs without writing files.")
    parser.add_argument("--no-recursive", action="store_true", help="For a folder, scan only its top level.")
    parser.add_argument("--subtitle", type=Path, help="Explicit subtitle file; valid only for a single audio input.")
    parser.add_argument(
        "--subtitle-suffix",
        default="",
        help="Use subtitles named <audio stem><suffix>.<ext>, for example --subtitle-suffix _zh.",
    )
    parser.add_argument("--no-subtitles", action="store_true", help="Do not search for same-name subtitle files.")
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG", "ffmpeg"), help="ffmpeg executable.")
    parser.add_argument("--ffprobe", default=os.environ.get("FFPROBE", "ffprobe"), help="ffprobe executable.")
    parser.add_argument("--percentile", type=float, default=0.995, help="Peak normalization percentile (default: 0.995).")
    parser.add_argument("--gamma", type=float, default=0.55, help="Amplitude compression gamma (default: 0.55).")
    args = parser.parse_args()
    if not 0 < args.percentile <= 1:
        parser.error("--percentile must be greater than 0 and at most 1")
    if args.gamma <= 0:
        parser.error("--gamma must be greater than 0")
    if args.subtitle and (args.input.is_dir() or args.no_subtitles):
        parser.error("--subtitle requires a single audio file and cannot be used with --no-subtitles")
    return args


def audio_inputs(source: Path, recursive: bool) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() not in AUDIO_EXTENSIONS:
            raise ValueError(f"Unsupported audio extension: {source.suffix}")
        return [source]
    if not source.is_dir():
        raise ValueError(f"Input path does not exist: {source}")
    iterator: Iterable[Path] = source.rglob("*") if recursive else source.glob("*")
    return sorted((item for item in iterator if item.is_file() and item.suffix.lower() in AUDIO_EXTENSIONS), key=lambda item: str(item).lower())


def read_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def timestamp(value: str) -> float | None:
    match = re.fullmatch(r"\s*(?:(\d+):)?(\d{1,2}):(\d{2})(?:[,.](\d{1,3}))?\s*", value)
    if not match:
        return None
    hours, minutes, seconds, fraction = match.groups()
    return (int(hours or 0) * 3600) + (int(minutes) * 60) + int(seconds) + (int(fraction or "0") / (10 ** len(fraction or "")))


def parse_srt_or_vtt(text: str) -> list[tuple[float, float, str]]:
    cues: list[tuple[float, float, str]] = []
    for block in re.split(r"\n\s*\n", text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        time_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            continue
        start_text, end_text = lines[time_index].split("-->", 1)
        start = timestamp(start_text)
        end = timestamp(end_text.strip().split(maxsplit=1)[0])
        if start is None or end is None:
            continue
        content = "\n".join(lines[time_index + 1:]).strip()
        if content:
            cues.append((start, max(end, start + 0.01), content))
    return cues


def parse_lrc(text: str, duration: float | None) -> list[tuple[float, float, str]]:
    entries: list[tuple[float, str]] = []
    for line in text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        matches = list(re.finditer(r"\[(\d+):(\d{2})(?:[.:](\d{1,3}))?\]", line))
        content = re.sub(r"\[[^\]]+\]", "", line).strip()
        if not matches or not content:
            continue
        for match in matches:
            fraction = match.group(3) or ""
            start = int(match.group(1)) * 60 + int(match.group(2))
            if fraction:
                start += int(fraction) / (10 ** len(fraction))
            entries.append((start, content))
    entries.sort(key=lambda entry: entry[0])
    return [
        (start, max(start + 0.01, entries[index + 1][0] if index + 1 < len(entries) else (duration or start + 3)), content)
        for index, (start, content) in enumerate(entries)
    ]


def subtitle_path(audio: Path, explicit: Path | None, enabled: bool, suffix: str = "") -> Path | None:
    if explicit:
        if not explicit.is_file():
            raise ValueError(f"Subtitle path does not exist: {explicit}")
        return explicit.resolve()
    if not enabled:
        return None
    for extension in SUBTITLE_EXTENSIONS:
        candidate = audio.with_name(f"{audio.stem}{suffix}{extension}")
        if candidate.is_file():
            return candidate
    return None


def probe_duration(audio: Path, ffprobe: str) -> float | None:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(audio)],
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        return None
    try:
        return float(completed.stdout.decode("utf-8", errors="replace").strip())
    except ValueError:
        return None


def decode_peak_magnitudes(audio: Path, ffmpeg: str) -> list[float]:
    process = subprocess.Popen(
        [ffmpeg, "-nostdin", "-v", "error", "-i", str(audio), "-f", "s16le", "-acodec", "pcm_s16le", "-ar", str(SAMPLE_RATE), "-ac", str(CHANNELS), "pipe:1"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    carry = b""
    peaks: list[float] = []
    while True:
        chunk = process.stdout.read(1024 * 1024)
        if not chunk:
            break
        buffer = carry + chunk
        complete_bytes = len(buffer) - (len(buffer) % WINDOW_BYTES)
        for offset in range(0, complete_bytes, WINDOW_BYTES):
            peak = audioop.max(buffer[offset:offset + WINDOW_BYTES], 2)
            peaks.append(peak / 32768.0)
        carry = buffer[complete_bytes:]
    stderr = process.stderr.read() if process.stderr else b""
    if process.wait() != 0:
        message = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(message or f"ffmpeg exited with code {process.returncode}")
    return peaks


def percentile(values: Sequence[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(max(0.0, value) for value in values)
    index = round((len(ordered) - 1) * ratio)
    return ordered[max(0, min(len(ordered) - 1, index))]


def wave_points(magnitudes: Sequence[float], ratio: float, gamma: float) -> tuple[list[tuple[float, float]], float]:
    reference = percentile(magnitudes, ratio) or 1.0
    compressed = [math.pow(min(1.0, max(0.0, value) / reference), gamma) for value in magnitudes]
    # This offset is deliberate: it matches legacy REC timing and its JS decoder.
    points = [(0.0, 0.0)]
    points.extend(((index + 1) * WINDOW_SECONDS, compressed[index]) for index in range(max(0, len(compressed) - 1)))
    return points, reference


def encode_wave(points: Sequence[tuple[float, float]]) -> str:
    payload = bytearray()
    for time_seconds, value in points:
        payload.extend(struct.pack("<dd", time_seconds * 100, min(1.0, max(0.0, value))))
    payload.extend(struct.pack("<dd", 0.0, 0.0))  # Legacy end sentinel.
    return base64.b64encode(payload).decode("ascii")


def serialize(points: Sequence[tuple[float, float]], cues: Sequence[tuple[float, float, str]], reference: float, percentile_value: float, gamma: float) -> str:
    wave = encode_wave(points)
    option = (
        " generator='release-tools-python-v1' interval='0.1'"
        f" percentile='{percentile_value:g}' gamma='{gamma:g}' peakReference='{reference:.8g}'"
    )
    tags = []
    for number, (start, end, text) in enumerate(cues, start=1):
        encoded_text = base64.b64encode(text.encode("utf-8")).decode("ascii")
        tags.append(
            f"<tag time1='{start:.2f}' time2='{end:.2f}' text='{encoded_text}'"
            f" input='' num='{number}' star='0' ng='0' ok='0' score='0' sy='0'/>"
        )
    return "\n".join([
        "<?xml version='1.0' encoding='UTF-8'?>",
        "<media version='1.0'>",
        f"<wave data='{wave}' bits='64'></wave>",
        f"<option{option}></option>",
        *tags,
        "</media>",
        "",
    ])


def cues_for(audio: Path, subtitle: Path | None, ffprobe: str) -> list[tuple[float, float, str]]:
    if subtitle is None:
        return []
    text = read_text(subtitle)
    if subtitle.suffix.lower() == ".lrc":
        return parse_lrc(text, probe_duration(audio, ffprobe))
    return parse_srt_or_vtt(text)


def main() -> int:
    args = parse_args()
    source = args.input.expanduser().resolve()
    try:
        inputs = audio_inputs(source, recursive=not args.no_recursive)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if not inputs:
        print(f"No supported audio files found under: {source}", file=sys.stderr)
        return 1

    created = skipped = failed = 0
    for audio in inputs:
        output = audio.with_suffix(".recx")
        if output.exists() and not args.overwrite:
            print(f"SKIP  {output} (already exists; use --overwrite)")
            skipped += 1
            continue
        try:
            subtitle = subtitle_path(audio, args.subtitle, not args.no_subtitles, args.subtitle_suffix)
            if args.dry_run:
                print(f"PLAN  {audio} -> {output}" + (f" (subtitle: {subtitle})" if subtitle else ""))
                continue
            magnitudes = decode_peak_magnitudes(audio, args.ffmpeg)
            points, reference = wave_points(magnitudes, args.percentile, args.gamma)
            cues = cues_for(audio, subtitle, args.ffprobe)
            output.write_text(serialize(points, cues, reference, args.percentile, args.gamma), encoding="utf-8", newline="\n")
            print(f"WRITE {output} ({len(points)} wave points, {len(cues)} subtitles)")
            created += 1
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            print(f"FAIL  {audio}: {error}", file=sys.stderr)
            failed += 1
    print(f"Summary: written={created}, skipped={skipped}, failed={failed}, total={len(inputs)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
