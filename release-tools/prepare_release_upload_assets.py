#!/usr/bin/env python3
"""Create zero-copy, upload-ready GitHub Release asset names for one folder."""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


def load_publisher_module(root: Path):
    script_path = root / "release-tools" / "publish_season_release.py"
    specification = importlib.util.spec_from_file_location("publish_season_release", script_path)
    if specification is None or specification.loader is None:
        raise SystemExit(f"Cannot load publisher helpers: {script_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, help="Source audio folder inside the repository.")
    parser.add_argument("--tag", required=True, help="Release tag, used as the staging subdirectory.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Local staging directory outside the repository.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    publisher = load_publisher_module(root)
    folder = publisher.resolve_folder(root, args.folder)
    stage = args.output_dir.resolve() / args.tag
    stage.mkdir(parents=True, exist_ok=True)

    audio_files = publisher.collect_audio(folder)
    staged = 0
    for audio in audio_files:
        relative_name = audio.relative_to(folder).as_posix()
        asset_name = publisher.github_release_asset_name(relative_name)
        destination = stage / asset_name
        if destination.exists():
            if destination.samefile(audio):
                continue
            raise SystemExit(f"Staging target already exists and is not the source file: {destination}")
        destination.hardlink_to(audio)
        staged += 1

    print(f"Prepared {len(audio_files)} upload assets in {stage} ({staged} new hard links).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
