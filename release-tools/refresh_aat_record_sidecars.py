#!/usr/bin/env python3
"""Refresh AAT GitHub Raw and jsDelivr RECX links without contacting GitHub."""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote


RECORD_NAME = "american-accent-training-4e-audio-v1.md"
RAW_BASE = "https://raw.githubusercontent.com/andylee1890/reciter-resources/main/"
CDN_BASE = "https://cdn.jsdelivr.net/gh/andylee1890/reciter-resources@main/"


def recx_link(base: str, filename: str) -> str:
    return f"[recx]({base}resources/AAT/{quote(filename)})"


def with_one_recx_link(value: str, link: str) -> str:
    """Keep every non-RECX sidecar link and append the canonical RECX link once."""
    parts = [part for part in value.split("<br>") if not part.strip().startswith("[recx](")]
    return "<br>".join([*parts, link])


def refresh(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    updated: list[str] = []
    rows = 0
    for line in lines:
        if line.startswith("| ") and not line.startswith("| ---") and "| Audio |" not in line:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) == 6 and cells[0].strip().endswith(".mp3"):
                filename = cells[0].strip()
                cells[4] = with_one_recx_link(cells[4].strip(), recx_link(RAW_BASE, filename[:-4] + ".recx"))
                cells[5] = with_one_recx_link(cells[5].strip(), recx_link(CDN_BASE, filename[:-4] + ".recx"))
                line = "| " + " | ".join(cells) + " |"
                rows += 1
        updated.append(line)
    marker = "- Internet Archive RECX uploaded:"
    if not any(line.startswith(marker) for line in updated):
        index = next(index for index, line in enumerate(updated) if line.startswith("- Internet Archive uploaded:"))
        updated.insert(index + 1, "- Internet Archive RECX uploaded: False")
    path.write_text("\n".join(updated) + "\n", encoding="utf-8", newline="\n")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh AAT RECX sidecar links in its public record.")
    parser.add_argument("--record", type=Path, default=Path("release-records") / RECORD_NAME)
    args = parser.parse_args()
    path = args.record.expanduser().resolve()
    print(f"Updated {refresh(path)} AAT record rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
