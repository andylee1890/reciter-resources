#!/usr/bin/env python3
"""Generate the public README resource catalog from the canonical release index."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any


CATALOG_START = "<!-- RESOURCE_CATALOG_START -->"
CATALOG_END = "<!-- RESOURCE_CATALOG_END -->"
SIDECAR_LABELS = {
    "srt": "SRT",
    "srtZh": "中译 SRT",
    "lrc": "LRC",
    "rec": "REC",
    "recx": "RECX",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def display_title(title: str) -> str:
    return re.sub(r"\s+Audio(?: v[0-9]+)?$", "", title)


def version_from_tag(tag: str) -> str:
    match = re.search(r"-(v[0-9][a-z0-9.-]*)$", tag)
    return match.group(1) if match else tag


def sidecar_labels(detail: dict[str, Any]) -> str:
    found = {
        extension
        for track in detail.get("audio", [])
        for extension in track.get("sidecars", {}).get("githubRaw", {})
    }
    labels = [label for extension, label in SIDECAR_LABELS.items() if extension in found]
    return " / ".join(labels) if labels else "配套文本"


def download_link(release: dict[str, Any]) -> str:
    release_url = release.get("releaseUrl")
    if isinstance(release_url, str) and release_url:
        return f"[GitHub Release]({release_url})"
    release_urls = release.get("platforms", {}).get("githubRelease", {}).get("releaseUrls", [])
    if isinstance(release_urls, list) and release_urls and isinstance(release_urls[0], str):
        return f"[GitHub Releases ({len(release_urls)} parts)]({release_urls[0]})"
    mirrors = release.get("platforms", {}).get("mirrors", [])
    for mirror in mirrors:
        if mirror.get("provider") == "internetArchive" and isinstance(mirror.get("itemUrl"), str):
            return f"[Internet Archive]({mirror['itemUrl']})"
    return f"[资源明细]({release['detailRaw']})"


def catalog_row(root: Path, release: dict[str, Any]) -> str:
    detail = load_json(root / "release-records" / release["detailFile"])
    poster_path = release["poster"]["card"]["path"]
    title = display_title(release["title"])
    poster = f'<img src="./{poster_path}" alt="{html.escape(title)}" width="72" />'
    content = f"{release['audioCount']} 条音频；可用 {sidecar_labels(detail)} 文本。"
    updated_at = release["createdAt"].split(" ", 1)[0]
    return " | ".join(
        (
            f'<div align="center">{poster}<br/><strong>{html.escape(title)}</strong></div>',
            content,
            updated_at,
            f"`{version_from_tag(release['tag'])}`",
            download_link(release),
        )
    )


def catalog_markdown(root: Path, index: dict[str, Any]) -> str:
    lines = [
        CATALOG_START,
        "资源海报、介绍、更新日期、版本和下载入口会保持同步。",
        "",
        "| 卡组 | 介绍 | 更新日期 | 版本 | 下载链接 |",
        "| :---: | --- | :---: | :---: | :---: |",
    ]
    lines.extend(f"| {catalog_row(root, release)} |" for release in index["releases"])
    lines.append(CATALOG_END)
    return "\n".join(lines)


def replace_catalog(readme_path: Path, content: str) -> None:
    raw = readme_path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode("utf-8")
    start = text.find(CATALOG_START)
    end = text.find(CATALOG_END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"{readme_path}: missing resource catalog markers")
    end += len(CATALOG_END)
    updated = text[:start] + content.replace("\n", newline) + text[end:]
    readme_path.write_bytes(updated.encode("utf-8"))


def parse_args() -> argparse.Namespace:
    root = repository_root()
    parser = argparse.ArgumentParser(description="Generate the README poster-backed resource catalog.")
    parser.add_argument("--readme", type=Path, default=root / "README.md")
    parser.add_argument("--index", type=Path, default=root / "release-records" / "index.json")
    parser.add_argument("--check", action="store_true", help="Fail when the README catalog is out of date.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = repository_root()
    index = load_json(args.index)
    catalog = catalog_markdown(root, index)
    existing = args.readme.read_text(encoding="utf-8")
    start = existing.find(CATALOG_START)
    end = existing.find(CATALOG_END)
    if start == -1 or end == -1 or end < start:
        raise SystemExit(f"{args.readme}: missing resource catalog markers")
    end += len(CATALOG_END)
    current_catalog = existing[start:end].replace("\r\n", "\n")
    if args.check:
        if current_catalog != catalog:
            raise SystemExit("README resource catalog is out of date; run generate_readme_catalog.py")
        print("README resource catalog is current")
        return 0
    replace_catalog(args.readme, catalog)
    print(f"Wrote {len(index['releases'])} resource rows to {args.readme}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
