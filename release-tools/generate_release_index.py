#!/usr/bin/env python3
"""Generate a machine-readable index from published release records."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any


METADATA_PATTERN = re.compile(r"^- (?P<key>[^:]+): (?P<value>.*)$")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_links(cell: str) -> dict[str, str]:
    return {label.lstrip("."): url for label, url in LINK_PATTERN.findall(cell)}


def parse_record(path: Path) -> dict[str, Any] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{path}: missing title")

    metadata: dict[str, str] = {}
    table_start: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        match = METADATA_PATTERN.match(line)
        if match:
            metadata[match.group("key")] = match.group("value")
        if line == "| Audio | Size MiB | Release asset | GitHub Raw sidecars | jsDelivr sidecars |":
            table_start = index + 2
            break

    required_metadata = ("Tag", "Repo", "Branch", "Folder", "Created at", "Audio files", "Total size", "Dry run", "Release")
    missing = [key for key in required_metadata if key not in metadata]
    if missing:
        raise ValueError(f"{path}: missing metadata: {', '.join(missing)}")
    if metadata["Dry run"].lower() != "false":
        return None
    if table_start is None:
        raise ValueError(f"{path}: missing files table")

    audio: list[dict[str, Any]] = []
    for line in lines[table_start:]:
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"{path}: malformed files table row")
        asset_links = parse_links(cells[2])
        if "mp3" not in asset_links:
            raise ValueError(f"{path}: missing mp3 link for {cells[0]}")
        audio.append(
            {
                "name": cells[0].replace(r"\|", "|"),
                "sizeMiB": float(cells[1]),
                "audioUrl": asset_links["mp3"],
                "sidecars": {
                    "githubRaw": parse_links(cells[3]),
                    "jsDelivr": parse_links(cells[4]),
                },
            }
        )

    expected_count = int(metadata["Audio files"])
    if len(audio) != expected_count:
        raise ValueError(f"{path}: expected {expected_count} audio rows, found {len(audio)}")

    total_size_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?) MiB", metadata["Total size"])
    if total_size_match is None:
        raise ValueError(f"{path}: invalid total size")

    return {
        "tag": metadata["Tag"].strip("`"),
        "title": lines[0][2:],
        "repository": metadata["Repo"].strip("`"),
        "branch": metadata["Branch"].strip("`"),
        "folder": metadata["Folder"].strip("`"),
        "createdAt": metadata["Created at"],
        "releaseUrl": metadata["Release"],
        "audioCount": expected_count,
        "totalSizeMiB": float(total_size_match.group(1)),
        "audio": audio,
    }


def generate_index(records_dir: Path) -> dict[str, Any]:
    releases: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for path in sorted(records_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        record = parse_record(path)
        if record is None:
            continue
        if record["tag"] in seen_tags:
            raise ValueError(f"Duplicate published release tag: {record['tag']}")
        seen_tags.add(record["tag"])
        releases.append(record)

    repositories = {release["repository"] for release in releases}
    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "repository": repositories.pop() if len(repositories) == 1 else None,
        "releases": releases,
    }


def parse_args() -> argparse.Namespace:
    root = repository_root()
    parser = argparse.ArgumentParser(description="Generate release-records/index.json from published release records.")
    parser.add_argument("--records-dir", type=Path, default=root / "release-records")
    parser.add_argument("--output", type=Path, default=root / "release-records" / "index.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records_dir = args.records_dir.resolve()
    output_path = args.output.resolve()
    if not records_dir.is_dir():
        raise SystemExit(f"Records directory not found: {records_dir}")

    index = generate_index(records_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(index['releases'])} published releases to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
