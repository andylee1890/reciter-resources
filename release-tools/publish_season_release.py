#!/usr/bin/env python3
"""Publish one resource folder's audio files to a GitHub Release.

The repository keeps text assets such as .srt, .lrc, .rec and .recx in Git.
Audio files are ignored by Git and uploaded as GitHub Release assets.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


SIDECAR_EXTENSIONS = (".srt", ".lrc", ".rec", ".recx")


def run(args: list[str], *, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=check,
        text=True,
        stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
        stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
    )


def repository_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"])
    return Path(result.stdout.strip()).resolve()


def safe_record_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "-", value).strip("-")


def markdown_cell(value: str) -> str:
    return value.replace("|", r"\|")


def markdown_link(label: str, url: str) -> str:
    return f"[{markdown_cell(label)}]({url})"


def quote_path(value: str) -> str:
    return quote(value, safe="/")


def quote_filename(value: str) -> str:
    return quote(value, safe="")


def raw_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{quote_path(branch)}/{quote_path(relative_path)}"


def jsdelivr_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{repo}@{quote_path(branch)}/{quote_path(relative_path)}"


def release_url(repo: str, tag: str) -> str:
    return f"https://github.com/{repo}/releases/tag/{quote_path(tag)}"


def release_asset_url(repo: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repo}/releases/download/{quote_path(tag)}/{quote_filename(filename)}"


def github_release_asset_name(filename: str) -> str:
    """Match GitHub's normalized display name for browser-uploaded assets."""
    path = Path(filename)
    normalized_stem = re.sub(r"[^A-Za-z0-9]+", ".", path.stem).strip(".")
    return f"{normalized_stem}{path.suffix}"


def resolve_folder(repo_root: Path, folder: str) -> Path:
    candidate = Path(folder)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    folder_path = candidate.resolve()
    try:
        folder_path.relative_to(repo_root)
    except ValueError as exc:
        raise SystemExit(f"Folder must stay inside repository root: {folder_path}") from exc
    if not folder_path.is_dir():
        raise SystemExit(f"Folder not found: {folder_path}")
    return folder_path


def collect_audio(folder_path: Path) -> list[Path]:
    files = sorted(folder_path.glob("*.mp3"), key=lambda p: p.name.lower())
    if not files:
        raise SystemExit(f"No .mp3 files found in {folder_path}")
    return files


def sidecars_for(audio: Path) -> list[str]:
    return [ext for ext in SIDECAR_EXTENSIONS if audio.with_suffix(ext).is_file()]


def sidecar_links(repo_root: Path, audio: Path, repo: str, branch: str, cdn: bool) -> str:
    links: list[str] = []
    for ext in sidecars_for(audio):
        sidecar = audio.with_suffix(ext)
        relative_path = sidecar.relative_to(repo_root).as_posix()
        url = jsdelivr_url(repo, branch, relative_path) if cdn else raw_url(repo, branch, relative_path)
        links.append(markdown_link(ext, url))
    return "<br>".join(links) if links else "-"


def write_release_record(
    repo_root: Path,
    folder_path: Path,
    tag: str,
    title: str,
    repo: str,
    branch: str,
    audio_files: list[Path],
    dry_run: bool,
) -> Path:
    record_dir = repo_root / "release-records"
    record_dir.mkdir(parents=True, exist_ok=True)
    record_path = record_dir / f"{safe_record_name(tag)}.md"
    relative_folder = folder_path.relative_to(repo_root).as_posix()
    total_bytes = sum(path.stat().st_size for path in audio_files)
    created_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")

    lines = [
        f"# {title}",
        "",
        f"- Tag: `{tag}`",
        f"- Repo: `{repo}`",
        f"- Branch: `{branch}`",
        f"- Folder: `{relative_folder}`",
        f"- Created at: {created_at}",
        f"- Audio files: {len(audio_files)}",
        f"- Total size: {total_bytes / 1024 / 1024:.2f} MiB",
        f"- Dry run: {dry_run}",
        f"- Release: {release_url(repo, tag)}",
        "",
        "## Link Bases",
        "",
        f"- GitHub Raw: `https://raw.githubusercontent.com/{repo}/{branch}/resources/...`",
        f"- jsDelivr: `https://cdn.jsdelivr.net/gh/{repo}@{branch}/resources/...`",
        f"- Release assets: `https://github.com/{repo}/releases/download/{tag}/...`",
        "",
        "## Files",
        "",
        "| Audio | Size MiB | Release asset | GitHub Raw sidecars | jsDelivr sidecars |",
        "| --- | ---: | --- | --- | --- |",
    ]

    for audio in audio_files:
        asset_url = release_asset_url(repo, tag, github_release_asset_name(audio.name))
        lines.append(
            f"| {markdown_cell(audio.name)} | {audio.stat().st_size / 1024 / 1024:.2f} | "
            f"{markdown_link('mp3', asset_url)} | "
            f"{sidecar_links(repo_root, audio, repo, branch, cdn=False)} | "
            f"{sidecar_links(repo_root, audio, repo, branch, cdn=True)} |"
        )

    record_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return record_path


def ensure_gh_available() -> None:
    if not shutil.which("gh"):
        raise SystemExit("GitHub CLI not found. Install gh and run `gh auth login` first.")


def release_exists(tag: str, repo: str) -> bool:
    result = subprocess.run(
        ["gh", "release", "view", tag, "--repo", repo],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def publish_release(tag: str, title: str, repo: str, record_path: Path, audio_files: list[Path], clobber: bool) -> None:
    ensure_gh_available()
    if not release_exists(tag, repo):
        subprocess.run(
            ["gh", "release", "create", tag, "--repo", repo, "--title", title, "--notes-file", str(record_path)],
            check=True,
        )
    else:
        print(f"Release {tag} already exists. Uploading assets to existing release.")

    args = ["gh", "release", "upload", tag, "--repo", repo]
    if clobber:
        args.append("--clobber")
    args.extend(str(path) for path in audio_files)
    subprocess.run(args, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload one folder of .mp3 files to a GitHub Release.")
    parser.add_argument("--folder", required=True, help="Resource folder, usually under resources/.")
    parser.add_argument("--tag", required=True, help="GitHub Release tag.")
    parser.add_argument("--title", required=True, help="GitHub Release title.")
    parser.add_argument("--repo", default="andylee1890/reciter-resources", help="owner/repo, default: %(default)s")
    parser.add_argument("--branch", default="main", help="Branch used by text resource links, default: %(default)s")
    parser.add_argument("--dry-run", action="store_true", help="Only write the release record; do not upload.")
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="Write a non-dry-run release record without creating or uploading a release.",
    )
    parser.add_argument("--clobber", action="store_true", help="Overwrite same-name assets in an existing release.")
    args = parser.parse_args(argv)
    if args.dry_run and args.record_only:
        parser.error("--dry-run and --record-only cannot be used together")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    repo_root = repository_root()
    folder_path = resolve_folder(repo_root, args.folder)
    audio_files = collect_audio(folder_path)
    record_path = write_release_record(
        repo_root=repo_root,
        folder_path=folder_path,
        tag=args.tag,
        title=args.title,
        repo=args.repo,
        branch=args.branch,
        audio_files=audio_files,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print(f"Dry run. Release record written to {record_path}")
        print(f"Would upload {len(audio_files)} mp3 files to {args.repo} release {args.tag}.")
        return 0

    if args.record_only:
        print(f"Release record written to {record_path}")
        print("Release creation and upload were skipped.")
        return 0

    publish_release(args.tag, args.title, args.repo, record_path, audio_files, args.clobber)
    print(f"Uploaded {len(audio_files)} files to {args.repo} release {args.tag}.")
    print(f"Release record written to {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
