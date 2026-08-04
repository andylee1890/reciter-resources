#!/usr/bin/env python3
"""Upload one planned resource package to Internet Archive.

Credentials are read only from IA_ACCESS_KEY and IA_SECRET_KEY, or from a
credentials JSON file outside this repository. The public release record keeps
only the stable identifier and public URLs.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ARCHIVE_HOST = "s3.us.archive.org"
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{identifier}"
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
SIDECAR_EXTENSIONS = (".srt", ".lrc", ".rec", ".recx")
CONTENT_TYPES = {
    ".mp3": "audio/mpeg",
    ".srt": "text/plain; charset=utf-8",
    ".lrc": "text/plain; charset=utf-8",
    ".rec": "text/plain; charset=utf-8",
    ".recx": "application/xml",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def quote_component(value: str) -> str:
    return quote(value, safe="")


def item_url(identifier: str) -> str:
    return f"https://archive.org/details/{quote_component(identifier)}"


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
    return entry


def resolve_package(root: Path, entry: dict[str, str]) -> tuple[Path, list[Path], list[Path]]:
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
    sidecars = sorted(
        (path for extension in SIDECAR_EXTENSIONS for path in folder.glob(f"*{extension}")),
        key=lambda path: path.name.lower(),
    )
    return folder, audio, [*audio, *sidecars]


def load_credentials(path: Path | None) -> tuple[str, str]:
    access_key = os.environ.get("IA_ACCESS_KEY", "").strip()
    secret_key = os.environ.get("IA_SECRET_KEY", "").strip()
    if access_key and secret_key:
        return access_key, secret_key
    if path is None:
        raise SystemExit(
            "Missing credentials. Set IA_ACCESS_KEY and IA_SECRET_KEY, or pass "
            "--credentials-file pointing to a private JSON file outside the repository."
        )
    resolved = path.expanduser().resolve()
    root = repository_root()
    try:
        resolved.relative_to(root)
    except ValueError:
        pass
    else:
        raise SystemExit("Credentials file must stay outside the repository.")
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read credentials file: {resolved}") from exc
    access_key = str(payload.get("access_key", "")).strip()
    secret_key = str(payload.get("secret_key", "")).strip()
    if not access_key or not secret_key:
        raise SystemExit("Credentials file must contain non-empty access_key and secret_key values.")
    return access_key, secret_key


def fetch_metadata(identifier: str) -> dict[str, Any] | None:
    request = Request(ARCHIVE_METADATA_URL.format(identifier=quote_component(identifier)))
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        body = exc.read(300).decode("utf-8", errors="replace")
        raise SystemExit(f"Internet Archive metadata request failed ({exc.code}): {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Internet Archive metadata request failed: {exc}") from exc


def remote_sizes(identifier: str) -> dict[str, int]:
    metadata = fetch_metadata(identifier)
    if metadata is None:
        return {}
    result: dict[str, int] = {}
    for entry in metadata.get("files", []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        size = entry.get("size")
        if not isinstance(name, str):
            continue
        try:
            result[name] = int(size)
        except (TypeError, ValueError):
            continue
    return result


def put_file(*, identifier: str, path: Path, headers: dict[str, str], retries: int) -> None:
    target = f"/{quote_component(identifier)}/{quote_component(path.name)}"
    for attempt in range(retries + 1):
        connection = http.client.HTTPSConnection(ARCHIVE_HOST, timeout=120, context=ssl.create_default_context())
        try:
            connection.putrequest("PUT", target)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(path.stat().st_size))
            connection.endheaders()
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    connection.send(chunk)
            response = connection.getresponse()
            body = response.read(500).decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                return
            if response.status not in RETRYABLE_STATUS or attempt == retries:
                raise SystemExit(f"Upload failed for {path.name} ({response.status}): {body}")
            delay = min(60, 2**attempt)
            print(f"{path.name}: server returned {response.status}; retrying in {delay}s", file=sys.stderr)
        except (OSError, http.client.HTTPException) as exc:
            if attempt == retries:
                raise SystemExit(f"Upload failed for {path.name}: {exc}") from exc
            delay = min(60, 2**attempt)
            print(f"{path.name}: {exc}; retrying in {delay}s", file=sys.stderr)
        finally:
            connection.close()
        time.sleep(delay)


def update_record(root: Path, tag: str, identifier: str) -> None:
    path = root / "release-records" / f"{tag}.md"
    if not path.is_file():
        raise SystemExit(f"Release record not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    replacements = {
        "Internet Archive identifier": f"`{identifier}`",
        "Internet Archive item": item_url(identifier),
        "Internet Archive uploaded": "True",
    }
    seen: set[str] = set()
    for index, line in enumerate(lines):
        for key, value in replacements.items():
            prefix = f"- {key}:"
            if line.startswith(prefix):
                lines[index] = f"{prefix} {value}"
                seen.add(key)
                break
    insertion = next((index for index, line in enumerate(lines) if line == ""), None)
    if insertion is None:
        raise SystemExit(f"Release record has no metadata block: {path}")
    for key, value in reversed(list(replacements.items())):
        if key not in seen:
            lines.insert(insertion, f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def generate_index(root: Path) -> None:
    subprocess.run([sys.executable, str(root / "release-tools" / "generate_release_index.py")], cwd=root, check=True)


def verify_files(identifier: str, audio: list[Path]) -> list[str]:
    sizes = remote_sizes(identifier)
    return [path.name for path in audio if sizes.get(path.name) != path.stat().st_size]


def wait_for_files(identifier: str, audio: list[Path], wait_seconds: int, poll_seconds: int) -> list[str]:
    deadline = time.monotonic() + wait_seconds
    while True:
        missing = verify_files(identifier, audio)
        if not missing or time.monotonic() >= deadline:
            return missing
        print(
            f"Waiting for Internet Archive metadata ({len(missing)} files not visible yet); retrying in {poll_seconds}s",
            file=sys.stderr,
        )
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload one release-plan audio and sidecar package to Internet Archive.")
    parser.add_argument("--tag", required=True, help="Existing release-plan tag to upload.")
    parser.add_argument("--identifier", help="IA item identifier, default: reciter-<tag>.")
    parser.add_argument("--credentials-file", type=Path, help="Private JSON credentials file outside the repository.")
    parser.add_argument("--collection", default="opensource_audio", help="IA collection metadata, default: %(default)s")
    parser.add_argument("--creator", default="Reciter Resources", help="IA creator metadata, default: %(default)s")
    parser.add_argument("--retries", type=int, default=4, help="Retries per failed file, default: %(default)s")
    parser.add_argument(
        "--verify-wait-seconds",
        type=int,
        default=300,
        help="Maximum metadata-ingestion wait after upload, default: %(default)s",
    )
    parser.add_argument(
        "--verify-poll-seconds",
        type=int,
        default=15,
        help="Metadata verification polling interval, default: %(default)s",
    )
    parser.add_argument("--dry-run", action="store_true", help="List the upload without changing Internet Archive or records.")
    parser.add_argument("--verify-only", action="store_true", help="Verify remote files and update local links only when complete.")
    parser.add_argument("--force", action="store_true", help="Re-upload files even when an equal-size remote file exists.")
    args = parser.parse_args(argv)
    if args.retries < 0 or args.verify_wait_seconds < 0 or args.verify_poll_seconds <= 0:
        parser.error("retry and wait values must be non-negative; polling interval must be positive")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    entry = load_plan_entry(root, args.tag)
    identifier = args.identifier or f"reciter-{args.tag}"
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise SystemExit("Identifier must contain 3-100 lowercase letters, digits, dots, underscores, or hyphens.")
    folder, audio, package_files = resolve_package(root, entry)
    total_size = sum(path.stat().st_size for path in package_files)
    existing = remote_sizes(identifier)
    pending = package_files if args.force else [path for path in package_files if existing.get(path.name) != path.stat().st_size]

    print(f"Internet Archive item: {item_url(identifier)}")
    print(
        f"Package: {folder.relative_to(root).as_posix()} "
        f"({len(audio)} MP3 + {len(package_files) - len(audio)} sidecars, {total_size / 1024 / 1024:.2f} MiB)"
    )
    print(f"Remote files already matching: {len(package_files) - len(pending)}; pending: {len(pending)}")
    if args.dry_run:
        return 0

    if not args.verify_only:
        access_key, secret_key = load_credentials(args.credentials_file)
        metadata_headers = {
            "Authorization": f"LOW {access_key}:{secret_key}",
            "x-amz-auto-make-bucket": "1",
            "x-archive-meta01-collection": args.collection,
            "x-archive-meta-mediatype": "audio",
            "x-archive-meta-title": entry["title"],
            "x-archive-meta-creator": args.creator,
            "x-archive-meta-description": "Audio package for language-study playback; matching text sidecars are linked from the reciter-resources repository.",
            "x-archive-size-hint": str(total_size),
            "x-archive-queue-derive": "0",
        }
        for index, path in enumerate(pending, start=1):
            print(f"[{index}/{len(pending)}] Uploading {path.name} ({path.stat().st_size / 1024 / 1024:.2f} MiB)")
            put_file(
                identifier=identifier,
                path=path,
                headers={**metadata_headers, "Content-Type": CONTENT_TYPES[path.suffix.lower()]},
                retries=args.retries,
            )

    missing = wait_for_files(identifier, package_files, args.verify_wait_seconds, args.verify_poll_seconds)
    if missing:
        print("Remote verification incomplete:", *missing, sep="\n", file=sys.stderr)
        return 2
    update_record(root, args.tag, identifier)
    generate_index(root)
    print(f"Verified {len(package_files)} files and updated release-records for {identifier}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
