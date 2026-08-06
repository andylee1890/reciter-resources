#!/usr/bin/env python3
"""Recover one package from its public GitHub links and publish IA direct files."""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import generate_release_index as release_index
import publish_to_internet_archive as ia


DOWNLOAD_CHUNK_SIZE = 256 * 1024


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def source_links(root: Path, tag: str) -> dict[str, str]:
    record = release_index.parse_record(root / "release-records" / f"{tag}.md")
    if record is None:
        raise SystemExit(f"Release record is not published: {tag}")
    links: dict[str, str] = {}
    for track in record["audio"]:
        links[track["name"]] = track["audioUrl"]
        stem = Path(track["name"]).stem
        for extension, url in track["sidecars"]["githubRaw"].items():
            filename = f"{stem}.{extension}"
            if filename in links and links[filename] != url:
                raise SystemExit(f"Conflicting public source link for {filename}")
            links[filename] = url
    return links


def content_length(response: object) -> int | None:
    value = response.headers.get("Content-Length")  # type: ignore[attr-defined]
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def download(url: str, destination: Path, retries: int) -> None:
    request = Request(url, headers={"User-Agent": "reciter-resources-ia-recovery/1"})
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=120) as response:
                expected_size = content_length(response)
                if destination.is_file() and expected_size is not None and destination.stat().st_size == expected_size:
                    return
                partial = destination.with_name(f"{destination.name}.part")
                destination.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with partial.open("wb") as target:
                    while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                        target.write(chunk)
                        written += len(chunk)
                if expected_size is not None and written != expected_size:
                    raise OSError(f"expected {expected_size} bytes, received {written}")
                partial.replace(destination)
                return
        except (HTTPError, URLError, OSError, TimeoutError) as exc:
            if attempt == retries:
                raise SystemExit(f"Download failed for {destination.name}: {exc}") from exc
            time.sleep(min(60, 5 * 2**attempt))
    raise AssertionError("unreachable")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover one release package from GitHub and upload individual Archive files.")
    parser.add_argument("--tag", required=True, help="Existing published release tag.")
    parser.add_argument("--staging-dir", type=Path, required=True, help="Directory outside the repository for temporary individual files.")
    parser.add_argument("--credentials-file", type=Path, help="Private IA credentials file outside the repository.")
    parser.add_argument("--retries", type=int, default=5, help="Retries per download or upload, default: %(default)s")
    parser.add_argument("--direct", action="store_true", help="Bypass HTTP(S) proxy variables for Internet Archive operations.")
    parser.add_argument("--keep-staging", action="store_true", help="Keep recovered files after remote verification succeeds.")
    parser.add_argument("--dry-run", action="store_true", help="List expected public source files without downloading or uploading.")
    args = parser.parse_args(argv)
    if args.retries < 0:
        parser.error("--retries must be non-negative")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    ia.load_plan_entry(root, args.tag)
    links = source_links(root, args.tag)
    package_dir = args.staging_dir.expanduser().resolve() / args.tag
    print(f"Package: {args.tag}; public files: {len(links)}; staging: {package_dir}")
    if args.dry_run:
        for filename in sorted(links, key=str.lower):
            print(filename)
        return 0

    for index, (filename, url) in enumerate(sorted(links.items(), key=lambda item: item[0].lower()), start=1):
        print(f"[{index}/{len(links)}] Downloading {filename}", flush=True)
        download(url, package_dir / filename, args.retries)

    command = [
        "--tag",
        args.tag,
        "--source-folder",
        str(package_dir),
        "--retries",
        str(args.retries),
    ]
    if args.credentials_file is not None:
        command.extend(["--credentials-file", str(args.credentials_file)])
    if args.direct:
        command.append("--direct")
    result = ia.main(command)
    if result == 0 and not args.keep_staging:
        shutil.rmtree(package_dir)
    return result


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
