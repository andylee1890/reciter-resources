#!/usr/bin/env python3
"""Remove legacy ZIP assets from planned Internet Archive items.

This is deliberately destructive only for the exact historic asset name
``<tag>.zip``. It never removes an item or an individually published resource.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import publish_to_internet_archive as ia


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plan_tags(root: Path) -> set[str]:
    path = root / "release-tools" / "release-plan.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise SystemExit(f"Invalid release plan: {path}")
    tags = {entry.get("tag") for entry in resources if isinstance(entry, dict)}
    if not all(isinstance(tag, str) for tag in tags):
        raise SystemExit(f"Invalid release plan: {path}")
    return tags


def remove_bundle_record(root: Path, tag: str) -> None:
    path = root / "release-records" / f"{tag}.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    retained = [line for line in lines if not line.startswith("- Internet Archive bundle:")]
    if retained == lines:
        return
    path.write_text("\n".join(retained) + "\n", encoding="utf-8", newline="\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove legacy ZIP assets from planned Internet Archive items.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Remove the exact historic ZIP asset for every planned package.")
    group.add_argument("--tag", action="append", dest="tags", help="Remove the exact historic ZIP asset for this tag; repeatable.")
    parser.add_argument("--credentials-file", type=Path, required=True, help="Private JSON credentials file outside the repository.")
    parser.add_argument("--retries", type=int, default=3, help="Retry metadata checks this many times, default: %(default)s")
    parser.add_argument("--direct", action="store_true", help="Bypass HTTP(S) proxy variables for Archive metadata checks.")
    parser.add_argument("--dry-run", action="store_true", help="List deletions without changing Archive or records.")
    args = parser.parse_args(argv)
    if args.retries < 0:
        parser.error("--retries must be non-negative")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    available = plan_tags(root)
    tags = sorted(available if args.all else set(args.tags))
    unknown = set(tags) - available
    if unknown:
        raise SystemExit(f"Unknown release-plan tags: {', '.join(sorted(unknown))}")

    access_key, secret_key = ia.load_credentials(args.credentials_file)
    removed = 0
    already_absent = 0
    for index, tag in enumerate(tags, start=1):
        identifier = f"reciter-{tag}"
        filename = f"{tag}.zip"
        remote = ia.remote_sizes(identifier, direct=args.direct, transport="pycurl")
        if filename not in remote:
            print(f"[{index}/{len(tags)}] Already absent: {identifier}/{filename}")
            if not args.dry_run:
                remove_bundle_record(root, tag)
            already_absent += 1
            continue
        print(f"[{index}/{len(tags)}] Remove: {identifier}/{filename}")
        if args.dry_run:
            continue

        ia.delete_file_pycurl(
            identifier=identifier,
            filename=filename,
            access_key=access_key,
            secret_key=secret_key,
            retries=args.retries,
        )
        for attempt in range(args.retries + 1):
            remote = ia.remote_sizes(identifier, direct=args.direct, transport="pycurl")
            if filename not in remote:
                remove_bundle_record(root, tag)
                removed += 1
                break
            if attempt == args.retries:
                raise SystemExit(f"Archive still reports {identifier}/{filename} after deletion")
            time.sleep(10)

    if not args.dry_run:
        ia.generate_index(root)
    print(f"Removed: {removed}; already absent: {already_absent}; planned: {len(tags)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
