#!/usr/bin/env python3
"""Create a publication record for an Internet Archive-only audio package.

The companion upload command publishes the package's MP3 and text sidecars to
Internet Archive individually. This script never calls GitHub Release APIs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote


SIDECAR_EXTENSIONS = (".srt", ".lrc", ".rec", ".recx")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def quote_path(value: str) -> str:
    return quote(value, safe="/")


def quote_filename(value: str) -> str:
    return quote(value, safe="")


def markdown_cell(value: str) -> str:
    return value.replace("|", r"\|")


def markdown_link(label: str, url: str) -> str:
    return f"[{markdown_cell(label)}]({url})"


def archive_item_url(identifier: str) -> str:
    return f"https://archive.org/details/{quote_filename(identifier)}"


def archive_download_url(identifier: str, filename: str) -> str:
    return f"https://archive.org/download/{quote_filename(identifier)}/{quote_filename(filename)}"


def raw_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{quote_path(branch)}/{quote_path(relative_path)}"


def jsdelivr_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{repo}@{quote_path(branch)}/{quote_path(relative_path)}"


def load_plan_entry(root: Path, tag: str) -> dict[str, str]:
    plan_path = root / "release-tools" / "release-plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read release plan: {plan_path}") from exc
    matches = [entry for entry in plan.get("resources", []) if entry.get("tag") == tag]
    if len(matches) != 1:
        raise SystemExit(f"Tag not found exactly once in {plan_path}: {tag}")
    entry = matches[0]
    if not all(isinstance(entry.get(key), str) for key in ("folder", "tag", "title")):
        raise SystemExit(f"Invalid plan entry for tag: {tag}")
    if entry.get("audioDelivery") != "internetArchive":
        raise SystemExit(f"Tag is not configured for Internet Archive-only delivery: {tag}")
    return entry


def sidecars_for(audio: Path) -> list[tuple[str, Path]]:
    sidecars: list[tuple[str, Path]] = []
    for extension in SIDECAR_EXTENSIONS:
        candidate = audio.with_suffix(extension)
        if candidate.is_file():
            sidecars.append((extension.lstrip("."), candidate))
    chinese_srt = audio.with_name(f"{audio.stem}_zh.srt")
    if chinese_srt.is_file():
        sidecars.append(("srtZh", chinese_srt))
    return sidecars


def sidecar_links(root: Path, audio: Path, repo: str, branch: str, cdn: bool) -> str:
    links: list[str] = []
    for label, sidecar in sidecars_for(audio):
        relative_path = sidecar.relative_to(root).as_posix()
        url = jsdelivr_url(repo, branch, relative_path) if cdn else raw_url(repo, branch, relative_path)
        links.append(markdown_link(label, url))
    return "<br>".join(links) if links else "-"


def write_record(root: Path, entry: dict[str, str], identifier: str, repo: str, branch: str) -> Path:
    folder = (root / entry["folder"]).resolve()
    try:
        folder.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Plan folder is outside repository: {folder}") from exc
    if not folder.is_dir():
        raise SystemExit(f"Plan folder does not exist: {folder}")
    audio = sorted(folder.glob("*.mp3"), key=lambda path: path.name.lower())
    if not audio:
        raise SystemExit(f"No MP3 files found in {folder}")

    record_path = root / "release-records" / f"{re.sub(r'[^A-Za-z0-9._-]', '-', entry['tag']).strip('-')}.md"
    if record_path.exists():
        raise SystemExit(f"Release record already exists: {record_path}")
    total_bytes = sum(path.stat().st_size for path in audio)
    created_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    relative_folder = folder.relative_to(root).as_posix()
    lines = [
        f"# {entry['title']}",
        "",
        f"- Tag: `{entry['tag']}`",
        "- Audio delivery: internetArchive",
        f"- Repo: `{repo}`",
        f"- Branch: `{branch}`",
        f"- Folder: `{relative_folder}`",
        f"- Created at: {created_at}",
        f"- Audio files: {len(audio)}",
        f"- Total size: {total_bytes / 1024 / 1024:.2f} MiB",
        "- Dry run: False",
        "- Published: False",
        "- Internet Archive uploaded: False",
        "",
        "## Link Bases",
        "",
        f"- Internet Archive item: {archive_item_url(identifier)}",
        f"- Internet Archive files: `https://archive.org/download/{identifier}/...`",
        f"- GitHub Raw sidecars: `https://raw.githubusercontent.com/{repo}/{branch}/resources/...`",
        f"- jsDelivr sidecars: `https://cdn.jsdelivr.net/gh/{repo}@{branch}/resources/...`",
        "",
        "## Files",
        "",
        "| Audio | Size MiB | Internet Archive file | GitHub Raw sidecars | jsDelivr sidecars |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for item in audio:
        lines.append(
            f"| {markdown_cell(item.name)} | {item.stat().st_size / 1024 / 1024:.2f} | "
            f"{markdown_link('mp3', archive_download_url(identifier, item.name))} | "
            f"{sidecar_links(root, item, repo, branch, cdn=False)} | "
            f"{sidecar_links(root, item, repo, branch, cdn=True)} |"
        )
    record_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return record_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create an Internet Archive-only package record from release-plan.json.")
    parser.add_argument("--tag", required=True, help="Archive-only release-plan tag.")
    parser.add_argument("--identifier", help="Internet Archive identifier, default: reciter-<tag>.")
    parser.add_argument("--repo", default="andylee1890/reciter-resources")
    parser.add_argument("--branch", default="main")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    entry = load_plan_entry(root, args.tag)
    record_path = write_record(root, entry, args.identifier or f"reciter-{args.tag}", args.repo, args.branch)
    print(f"Wrote Archive-only release record: {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
