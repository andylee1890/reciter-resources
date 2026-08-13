"""Generate per-poster card derivatives and update the local artwork index.

The source poster files are never modified. Each card uses a per-file focal
point and either a crop or a contain-style composition so titles, faces, and
season labels remain visible.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image


POSTER_DIR = Path(__file__).resolve().parents[0].parent / "artwork" / "posters"
INDEX_PATH = POSTER_DIR / "index.local.json"
CARD_DIR = POSTER_DIR / "card"

# Normalized crop settings are intentionally explicit per source file. The
# card is a full-bleed 4:5 crop; the y coordinate keeps the important part of
# each individual cover in frame instead of applying a blind center crop.
LAYOUTS = {
    "american-accent-training-4e.webp": {"mode": "crop", "y": 0.00},
    "cet4.webp": {"mode": "crop", "y": 0.00},
    "friends-s01.webp": {"mode": "crop", "y": 0.00},
    "friends-s02.webp": {"mode": "crop", "y": 0.01},
    "friends-s03.webp": {"mode": "crop", "y": 0.00},
    "friends-s04.webp": {"mode": "crop", "y": 0.01},
    "friends-s05.webp": {"mode": "crop", "y": 0.00},
    "friends-s06.webp": {"mode": "crop", "y": 0.01},
    "friends-s07.webp": {"mode": "crop", "y": 0.00},
    "friends-s08.webp": {"mode": "crop", "y": 0.01},
    "friends-s09.webp": {"mode": "crop", "y": 0.00},
    "friends-s10.webp": {"mode": "crop", "y": 0.01},
    "new-concept-english-1-official.webp": {"mode": "crop", "y": 0.00},
    "new-concept-english-2-official.webp": {"mode": "crop", "y": 0.00},
    "new-concept-english-3-official.webp": {"mode": "crop", "y": 0.01},
    "new-concept-english-4.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s01.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s02.webp": {"mode": "crop", "y": 0.01},
    "the-big-bang-theory-s03.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s04.webp": {"mode": "crop", "y": 0.01},
    "the-big-bang-theory-s05.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s06.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s07.webp": {"mode": "crop", "y": 0.01},
    "the-big-bang-theory-s08.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s09.webp": {"mode": "crop", "y": 0.00},
    "the-big-bang-theory-s10.webp": {"mode": "crop", "y": 0.01},
    "the-big-bang-theory-s11.webp": {"mode": "crop", "y": 0.00},
    "the-office-us-s01.webp": {"mode": "crop", "y": 0.00},
    "the-office-us-s02.webp": {"mode": "crop", "y": 0.01},
    "the-office-us-s03.webp": {"mode": "crop", "y": 0.00},
    "the-office-us-s04.webp": {"mode": "crop", "y": 0.01},
    "the-office-us-s05.webp": {"mode": "crop", "y": 0.00},
    "the-office-us-s06.webp": {"mode": "crop", "y": 0.01},
    "the-office-us-s07.webp": {"mode": "crop", "y": 0.00},
    "the-office-us-s08.webp": {"mode": "crop", "y": 0.01},
    "the-office-us-s09.webp": {"mode": "crop", "y": 0.00},
    "yes-minister.webp": {"mode": "crop", "y": 0.01},
    "yes-prime-minister.webp": {"mode": "crop", "y": 0.00},
}


def poster_files() -> list[Path]:
    return sorted(
        path
        for path in POSTER_DIR.glob("*.webp")
        if path.name != "index.local.json"
    )


def card_name(source_name: str) -> str:
    return source_name


def make_card(source: Path, target: Path, width: int, height: int) -> dict[str, object]:
    with Image.open(source) as original:
        image = original.convert("RGB")
        config = LAYOUTS.get(source.name, {"mode": "crop", "y": 0.00})
        target_ratio = width / height
        crop_height = min(image.height, round(image.width / target_ratio))
        max_y = image.height - crop_height
        top = round(max_y * float(config["y"]))
        box = (0, top, image.width, top + crop_height)
        image.crop(box).resize((width, height), Image.Resampling.LANCZOS).save(
            target, "WEBP", quality=86, method=6
        )
        return {
            "mode": config["mode"],
            "aspectRatio": f"{width}:{height}",
            "width": width,
            "height": height,
            "fit": "cover",
            "crop": {
                "x": 0.0,
                "y": round(top / image.height, 4),
                "width": 1.0,
                "height": round(crop_height / image.height, 4),
            },
            "sourceSize": {"width": image.width, "height": image.height},
        }


def update_index(card_data: dict[str, dict[str, object]]) -> None:
    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    for item in index["items"]:
        card = card_data.get(item["file"])
        if card is None:
            continue
        item["card"] = {
            "file": f"card/{item['file']}",
            **card,
        }
    INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=480)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    files = poster_files()
    if not files:
        raise SystemExit(f"no poster files found in {POSTER_DIR}")
    if not args.dry_run:
        CARD_DIR.mkdir(parents=True, exist_ok=True)
    card_data: dict[str, dict[str, object]] = {}
    for source in files:
        target = CARD_DIR / card_name(source.name)
        if args.dry_run:
            print(f"{source.name} -> {target.relative_to(POSTER_DIR)}")
            continue
        card_data[source.name] = make_card(source, target, args.width, args.height)
        print(f"{source.name} -> {target.relative_to(POSTER_DIR)}")
    if not args.dry_run:
        update_index(card_data)


if __name__ == "__main__":
    main()
