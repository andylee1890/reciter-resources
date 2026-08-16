#!/usr/bin/env python3
"""Publish AAT audio to seven resumable GitHub Release parts.

The script never deletes, replaces, or renames local source files. It creates
at most one release per part and skips a remote asset only when its name (or
label) and byte size already match the local MP3. The published AAT record and
indexes are updated only after every part passes remote verification.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


API_ROOT = "https://api.github.com"
ARCHIVE_IDENTIFIER = "reciter-american-accent-training-4e-audio-v1"
SIDECAR_EXTENSIONS = (".srt", ".lrc", ".rec", ".recx")
PART_TABLE_HEADER = (
    "| Audio | Size MiB | GitHub Release asset | Internet Archive file | GitHub Raw sidecars | jsDelivr sidecars |"
)


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


def raw_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{quote_path(branch)}/{quote_path(relative_path)}"


def jsdelivr_url(repo: str, branch: str, relative_path: str) -> str:
    return f"https://cdn.jsdelivr.net/gh/{repo}@{quote_path(branch)}/{quote_path(relative_path)}"


def archive_url(filename: str) -> str:
    return f"https://archive.org/download/{ARCHIVE_IDENTIFIER}/{quote_filename(filename)}"


def release_tag(base_tag: str, part_number: int) -> str:
    match = re.fullmatch(r"(?P<stem>.+)-(?P<version>v[0-9]+)", base_tag)
    if match is None:
        raise ValueError(f"Base tag must end in -v<number>: {base_tag}")
    return f"{match.group('stem')}-part-{part_number:02d}-{match.group('version')}"


def collect_audio(folder: Path) -> list[Path]:
    files = sorted(folder.glob("*.mp3"), key=lambda path: path.name.lower())
    if not files:
        raise SystemExit(f"No MP3 files found in {folder}")
    return files


def partition(audio: list[Path], part_size: int) -> list[list[Path]]:
    if part_size <= 0:
        raise ValueError("part_size must be positive")
    return [audio[index : index + part_size] for index in range(0, len(audio), part_size)]


def request_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    retries: int = 5,
) -> tuple[int, dict[str, Any] | list[Any] | None, dict[str, str]]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "reciter-resources-aat-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(1, retries + 1):
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=120) as response:
                raw = response.read()
                body = json.loads(raw.decode("utf-8")) if raw else None
                return response.status, body, dict(response.headers.items())
        except HTTPError as exc:
            if exc.code == 404:
                return 404, None, dict(exc.headers.items())
            if exc.code not in (408, 409, 422, 429, 500, 502, 503, 504) or attempt == retries:
                message = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"GitHub API {method} {url} returned {exc.code}: {message[:500]}") from exc
        except URLError as exc:
            if attempt == retries:
                raise RuntimeError(f"GitHub API {method} {url} failed: {exc}") from exc
        time.sleep(min(30, attempt * 3))
    raise AssertionError("unreachable")


def upload_asset(upload_url: str, asset: Path, token: str, retries: int) -> dict[str, Any]:
    endpoint = upload_url.split("{", 1)[0]
    query = f"name={quote_filename(asset.name)}&label={quote_filename(asset.name)}"
    url = f"{endpoint}?{query}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": content_type(asset),
        "User-Agent": "reciter-resources-aat-publisher",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = asset.read_bytes()
    for attempt in range(1, retries + 1):
        request = Request(url, data=payload, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=600) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")
            if exc.code == 422 and "already_exists" in message:
                raise FileExistsError(asset.name) from exc
            if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == retries:
                raise RuntimeError(f"Upload failed for {asset.name}: HTTP {exc.code}: {message[:500]}") from exc
        except URLError as exc:
            if attempt == retries:
                raise RuntimeError(f"Upload failed for {asset.name}: {exc}") from exc
        time.sleep(min(60, attempt * 5))
    raise AssertionError("unreachable")


def content_type(path: Path) -> str:
    return {
        ".mp3": "audio/mpeg",
        ".recx": "application/xml",
    }.get(path.suffix.lower(), "application/octet-stream")


def list_assets(release: dict[str, Any], repo: str, token: str, retries: int) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    page = 1
    while True:
        _, body, _ = request_json(
            "GET",
            f"{API_ROOT}/repos/{repo}/releases/{release['id']}/assets?per_page=100&page={page}",
            token,
            retries=retries,
        )
        if not isinstance(body, list):
            raise RuntimeError(f"Invalid asset response for release {release['tag_name']}")
        assets.extend(item for item in body if isinstance(item, dict))
        if len(body) < 100:
            return assets
        page += 1


def asset_map(assets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for asset in assets:
        for key in (asset.get("label"), asset.get("name")):
            if isinstance(key, str) and key:
                mapped[key] = asset
    return mapped


def github_web_asset_name(filename: str) -> str:
    """Match the filename rewriting performed by the GitHub release web form."""
    special_transliterations = {"æ": "ae", "Æ": "AE"}
    transliterated: list[str] = []
    for character in filename:
        if character in special_transliterations:
            transliterated.append(special_transliterations[character])
            continue
        decomposed = unicodedata.normalize("NFKD", character)
        ascii_characters = "".join(part for part in decomposed if ord(part) < 128 and not unicodedata.combining(part))
        transliterated.append(ascii_characters or character)
    normalized = re.sub(r"[^A-Za-z0-9_.+-]+", ".", "".join(transliterated))
    return re.sub(r"\.{2,}", ".", normalized)


def find_remote_asset(mapped: dict[str, dict[str, Any]], local_name: str) -> dict[str, Any] | None:
    """Find an asset by its API name/label or the web form's normalized filename."""
    return mapped.get(local_name) or mapped.get(github_web_asset_name(local_name))


def get_or_create_release(
    repo: str, tag: str, title: str, notes: str, token: str, retries: int
) -> dict[str, Any]:
    status, body, _ = request_json(
        "GET", f"{API_ROOT}/repos/{repo}/releases/tags/{quote_filename(tag)}", token, retries=retries
    )
    if status == 200 and isinstance(body, dict):
        return body
    if status != 404:
        raise RuntimeError(f"Unexpected status while looking up release {tag}: {status}")
    _, body, _ = request_json(
        "POST",
        f"{API_ROOT}/repos/{repo}/releases",
        token,
        {"tag_name": tag, "name": title, "body": notes, "draft": False, "prerelease": False},
        retries=retries,
    )
    if not isinstance(body, dict):
        raise RuntimeError(f"Invalid create-release response for {tag}")
    return body


def get_release(repo: str, tag: str, token: str, retries: int) -> dict[str, Any]:
    status, body, _ = request_json(
        "GET", f"{API_ROOT}/repos/{repo}/releases/tags/{quote_filename(tag)}", token, retries=retries
    )
    if status == 404:
        raise RuntimeError(f"Release {tag} does not exist")
    if status != 200 or not isinstance(body, dict):
        raise RuntimeError(f"Invalid lookup response for release {tag}: {status}")
    return body


def verify_part(
    release: dict[str, Any], files: list[Path], repo: str, token: str, retries: int
) -> dict[str, dict[str, Any]]:
    mapped = asset_map(list_assets(release, repo, token, retries))
    verified: dict[str, dict[str, Any]] = {}
    for item in files:
        asset = find_remote_asset(mapped, item.name)
        if asset is None:
            raise RuntimeError(f"Release {release['tag_name']} is missing asset: {item.name}")
        if asset.get("size") != item.stat().st_size:
            raise RuntimeError(
                f"Release {release['tag_name']} size mismatch for {item.name}: "
                f"remote {asset.get('size')} != local {item.stat().st_size}"
            )
        if not isinstance(asset.get("browser_download_url"), str):
            raise RuntimeError(f"Release {release['tag_name']} has no download URL for {item.name}")
        verified[item.name] = asset
    return verified


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


def release_assets(audio_files: list[Path]) -> list[Path]:
    assets: list[Path] = []
    for audio in audio_files:
        assets.append(audio)
        recx = audio.with_suffix(".recx")
        if recx.is_file():
            assets.append(recx)
    return assets


def sidecar_links(root: Path, audio: Path, repo: str, branch: str, cdn: bool) -> str:
    links: list[str] = []
    for label, sidecar in sidecars_for(audio):
        relative = sidecar.relative_to(root).as_posix()
        url = jsdelivr_url(repo, branch, relative) if cdn else raw_url(repo, branch, relative)
        links.append(markdown_link(label, url))
    return "<br>".join(links) if links else "-"


def write_completed_record(
    root: Path,
    folder: Path,
    base_tag: str,
    title: str,
    repo: str,
    branch: str,
    release_parts: list[tuple[dict[str, Any], list[Path], dict[str, dict[str, Any]]]],
) -> Path:
    files = [item for _, part_files, _ in release_parts for item in part_files]
    asset_urls = {name: asset["browser_download_url"] for _, _, assets in release_parts for name, asset in assets.items()}
    release_urls = [str(release["html_url"]) for release, _, _ in release_parts]
    record_path = root / "release-records" / f"{base_tag}.md"
    created_at = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    total_bytes = sum(item.stat().st_size for item in files)
    lines = [
        f"# {title}",
        "",
        f"- Tag: `{base_tag}`",
        "- Audio delivery: githubReleaseParts",
        f"- Repo: `{repo}`",
        f"- Branch: `{branch}`",
        f"- Folder: `{folder.relative_to(root).as_posix()}`",
        f"- Created at: {created_at}",
        f"- Audio files: {len(files)}",
        f"- Total size: {total_bytes / 1024 / 1024:.2f} MiB",
        "- Dry run: False",
        "- Published: True",
        "- Internet Archive uploaded: True",
        f"- Internet Archive identifier: `{ARCHIVE_IDENTIFIER}`",
        f"- Internet Archive item: https://archive.org/details/{ARCHIVE_IDENTIFIER}",
        f"- GitHub Release parts: {', '.join(release_urls)}",
        "",
        "## Link Bases",
        "",
        f"- GitHub Release parts: {len(release_parts)} releases, 70 audio files maximum per release.",
        f"- Internet Archive item: https://archive.org/details/{ARCHIVE_IDENTIFIER}",
        f"- GitHub Raw sidecars: `https://raw.githubusercontent.com/{repo}/{branch}/resources/...`",
        f"- jsDelivr sidecars: `https://cdn.jsdelivr.net/gh/{repo}@{branch}/resources/...`",
        "",
        "## Files",
        "",
        PART_TABLE_HEADER,
        "| --- | ---: | --- | --- | --- | --- |",
    ]
    for item in files:
        lines.append(
            f"| {markdown_cell(item.name)} | {item.stat().st_size / 1024 / 1024:.2f} | "
            f"{markdown_link('mp3', asset_urls[item.name])} | "
            f"{markdown_link('mp3', archive_url(item.name))} | "
            f"{sidecar_links(root, item, repo, branch, cdn=False)} | "
            f"{sidecar_links(root, item, repo, branch, cdn=True)} |"
        )
    record_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return record_path


def regenerate_public_indexes(root: Path) -> None:
    for script in ("generate_release_index.py", "generate_readme_catalog.py"):
        subprocess.run([sys.executable, str(root / "release-tools" / script)], check=True, cwd=root)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish AAT to seven resumable GitHub Release parts.")
    parser.add_argument("--folder", default="resources/AAT")
    parser.add_argument("--tag", default="american-accent-training-4e-audio-v1")
    parser.add_argument("--title", default="American Accent Training 4e Audio")
    parser.add_argument("--repo", default="andylee1890/reciter-resources")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--part-size", type=int, default=70)
    parser.add_argument("--token-env", default="GITHUB_TOKEN", help="Environment variable holding a GitHub token.")
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--between-parts-seconds", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Print the seven-part plan without GitHub API calls.")
    parser.add_argument("--verify-only", action="store_true", help="Verify remote parts and do not create or upload assets.")
    parser.add_argument(
        "--record-only",
        action="store_true",
        help="Rebuild the public record from existing MP3 Release assets without uploading anything.",
    )
    parser.add_argument(
        "--no-update-index",
        action="store_true",
        help="Do not rewrite the AAT record or indexes after complete verification.",
    )
    args = parser.parse_args()
    if args.part_size != 70:
        parser.error("AAT publishing uses a fixed 70-file part size")
    if args.retries < 1:
        parser.error("--retries must be positive")
    if args.between_parts_seconds < 0:
        parser.error("--between-parts-seconds cannot be negative")
    return args


def main() -> int:
    args = parse_args()
    root = repository_root()
    folder = (root / args.folder).resolve()
    try:
        folder.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"Folder must stay inside the repository: {folder}") from exc
    audio = collect_audio(folder)
    parts = partition(audio, args.part_size)
    if len(parts) != 7:
        raise SystemExit(f"Expected seven AAT parts of at most 70 files, found {len(parts)} for {len(audio)} files")

    for number, files in enumerate(parts, start=1):
        print(
            f"Part {number:02d}/07: {len(files)} files, {files[0].name} .. {files[-1].name}, "
            f"tag {release_tag(args.tag, number)}"
        )
    if args.dry_run:
        return 0

    token = os.environ.get(args.token_env, "")
    if not token and not args.verify_only and not args.record_only:
        raise SystemExit(f"Missing GitHub API token in environment variable {args.token_env}")

    completed: list[tuple[dict[str, Any], list[Path], dict[str, dict[str, Any]]]] = []
    for number, files in enumerate(parts, start=1):
        tag = release_tag(args.tag, number)
        title = f"{args.title} Part {number:02d} of 07"
        notes = f"{args.title} - part {number:02d} of 07. Contains {len(files)} individual audio files."
        release = (
            get_release(args.repo, tag, token, args.retries)
            if args.verify_only or args.record_only
            else get_or_create_release(args.repo, tag, title, notes, token, args.retries)
        )
        if args.record_only:
            verified = verify_part(release, files, args.repo, token, args.retries)
            completed.append((release, files, verified))
            print(f"{tag}: existing MP3 assets verified for record refresh")
            continue
        current = asset_map(list_assets(release, args.repo, token, args.retries))
        assets = release_assets(files)
        for item in assets:
            remote = find_remote_asset(current, item.name)
            if remote is not None and remote.get("size") == item.stat().st_size:
                print(f"{tag}: already verified {item.name}")
                continue
            if remote is not None:
                raise RuntimeError(f"{tag}: remote asset conflicts with local file: {item.name}")
            if args.verify_only:
                raise RuntimeError(f"{tag}: missing asset in verify-only mode: {item.name}")
            print(f"{tag}: uploading {item.name}")
            try:
                upload_asset(str(release["upload_url"]), item, token, args.retries)
            except FileExistsError:
                pass
        verified = verify_part(release, assets, args.repo, token, args.retries)
        completed.append((release, files, verified))
        print(f"{tag}: verified {len(verified)} of {len(files)} assets")
        if number < len(parts) and args.between_parts_seconds:
            time.sleep(args.between_parts_seconds)

    if args.no_update_index:
        print("All seven parts are verified. Index update was disabled.")
        return 0
    record_path = write_completed_record(root, folder, args.tag, args.title, args.repo, args.branch, completed)
    regenerate_public_indexes(root)
    print(f"All seven parts are verified. Updated record and indexes: {record_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
