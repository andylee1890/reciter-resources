#!/usr/bin/env python3
"""Normalize TOEFL resource basenames without changing file contents.

The source names use ``#`` as a number marker. That character has special
meaning in several upload tools, so audio and matching text sidecars are
renamed to stable names such as ``toefl-dialogue-016-商业.mp3``.

The command is a dry run unless ``--write`` is supplied. It never deletes a
file; renaming is performed in two phases so an interrupted run leaves the
data present under either its old or temporary name.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


CATEGORY_PREFIXES = {
    "对话": "toefl-dialogue",
    "公告": "toefl-announcement",
    "学术讲座": "toefl-lecture",
}
SUPPORTED_EXTENSIONS = {".mp3", ".srt", ".recx"}
SOURCE_PATTERN = re.compile(r"^【(?P<category>[^】]+)】#(?P<number>\d+)-(?P<topic>.+)$")


def build_mapping(root: Path) -> list[tuple[Path, Path]]:
    mapping: list[tuple[Path, Path]] = []
    for source in sorted(root.rglob("*"), key=lambda path: str(path).lower()):
        if not source.is_file() or source.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        match = SOURCE_PATTERN.fullmatch(source.stem)
        if not match:
            if "#" in source.name:
                raise SystemExit(f"Unrecognized filename containing #: {source}")
            continue
        category = match.group("category")
        try:
            prefix = CATEGORY_PREFIXES[category]
        except KeyError as exc:
            raise SystemExit(f"Unknown TOEFL category in filename: {source}") from exc
        topic = match.group("topic").replace("#", "-")
        new_stem = f"{prefix}-{int(match.group('number')):03d}-{topic}"
        mapping.append((source, source.with_name(new_stem + source.suffix)))
    return mapping


def validate_mapping(mapping: list[tuple[Path, Path]]) -> None:
    targets = [target for _, target in mapping]
    if len(set(targets)) != len(targets):
        raise SystemExit("Filename normalization would create duplicate targets.")
    sources = {source.resolve() for source, _ in mapping}
    for source, target in mapping:
        if target.exists() and target.resolve() not in sources:
            raise SystemExit(f"Target already exists: {target}")


def apply_mapping(mapping: list[tuple[Path, Path]]) -> None:
    staged: list[tuple[Path, Path]] = []
    for index, (source, target) in enumerate(mapping, start=1):
        temporary = source.with_name(f".toefl-normalize-{index:04d}{source.suffix}")
        if temporary.exists():
            raise SystemExit(f"Temporary path already exists: {temporary}")
        source.rename(temporary)
        staged.append((temporary, target))
    for temporary, target in staged:
        temporary.rename(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="resources/托福听力", type=Path)
    parser.add_argument("--write", action="store_true", help="Apply the planned renames.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Directory not found: {root}")
    mapping = build_mapping(root)
    validate_mapping(mapping)
    for source, target in mapping:
        print(f"{source} -> {target}")
    print(f"Planned renames: {len(mapping)}")
    if args.write:
        apply_mapping(mapping)
        print("Renames applied; no files were deleted.")
    else:
        print("Dry run only. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
