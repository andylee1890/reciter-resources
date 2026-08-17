#!/usr/bin/env python3
"""Register prepared Cambridge IELTS and TOEFL cover files in the public index."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
POSTER_DIR = ROOT / "artwork" / "posters"
INDEX_PATH = POSTER_DIR / "index.json"


def poster_specs() -> list[tuple[str, str, str]]:
    cambridge = [
        (f"cambridge-ielts-{number:02d}", f"cambridge-ielts-{number:02d}-listening-v1", "book-cover")
        for number in range(5, 21)
    ]
    toefl = [
        ("toefl-listening-dialogues", "toefl-listening-dialogues-v1", "collection-cover"),
        ("toefl-listening-announcements", "toefl-listening-announcements-v1", "collection-cover"),
        ("toefl-listening-lectures", "toefl-listening-lectures-v1", "collection-cover"),
    ]
    return cambridge + toefl


def poster_entry(identifier: str, tag: str, kind: str) -> dict[str, object]:
    original = POSTER_DIR / f"{identifier}.webp"
    card = POSTER_DIR / "card" / f"{identifier}.webp"
    if not original.is_file() or not card.is_file():
        raise SystemExit(f"Poster and card must exist for {identifier}")

    with Image.open(original) as image:
        width, height = image.size
    crop_height = min(height, round(width / (480 / 600)))
    return {
        "id": identifier,
        "kind": kind,
        "sourceType": "publisher-cover-image",
        "original": {"path": original.relative_to(ROOT).as_posix()},
        "card": {
            "path": card.relative_to(ROOT).as_posix(),
            "mode": "crop",
            "aspectRatio": "480:600",
            "width": 480,
            "height": 600,
            "fit": "cover",
            "crop": {
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": round(crop_height / height, 4),
            },
            "sourceSize": {"width": width, "height": height},
        },
        "usedBy": tag,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        action="append",
        required=True,
        help="Release tag to register; repeat for multiple published releases.",
    )
    parser.add_argument("--write", action="store_true", help="Update artwork/posters/index.json.")
    parser.add_argument(
        "--prune-unselected",
        action="store_true",
        help="Remove prepared entries for this tool's other, not-yet-published tags.",
    )
    args = parser.parse_args()

    data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    selected = [spec for spec in poster_specs() if spec[1] in set(args.tag)]
    if len(selected) != len(set(args.tag)):
        known_tags = {spec[1] for spec in poster_specs()}
        unknown = sorted(set(args.tag) - known_tags)
        raise SystemExit(f"Unknown resource poster tag(s): {', '.join(unknown)}")
    selected_ids = {spec[0] for spec in selected}
    if args.prune_unselected:
        managed_ids = {spec[0] for spec in poster_specs()}
        data["posters"] = [
            item for item in data["posters"] if item["id"] not in managed_ids or item["id"] in selected_ids
        ]
    existing = {item["id"] for item in data["posters"]}
    additions = [poster_entry(*spec) for spec in selected if spec[0] not in existing]
    for item in additions:
        print(f"{item['id']} -> {item['usedBy']}")

    if not args.write:
        print(f"Dry run: {len(additions)} poster entries would be registered.")
        return 0

    data["posters"].extend(additions)
    INDEX_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Registered {len(additions)} poster entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
