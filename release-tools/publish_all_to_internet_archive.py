#!/usr/bin/env python3
"""Sequentially publish planned resource packages to Internet Archive.

The script only reads release-tools/release-plan.json. It skips packages whose
release record already confirms a complete Internet Archive upload, so it can
be safely restarted after a network interruption.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_plan(root: Path) -> list[dict[str, str]]:
    path = root / "release-tools" / "release-plan.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read release plan: {path}") from exc
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise SystemExit(f"Invalid release plan: {path}")
    result: list[dict[str, str]] = []
    for entry in resources:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in ("tag", "folder", "title")):
            raise SystemExit(f"Invalid release plan entry: {entry!r}")
        result.append(entry)
    return result


def archive_uploaded(root: Path, tag: str) -> bool:
    record = root / "release-records" / f"{tag}.md"
    if not record.is_file():
        return False
    return any(line == "- Internet Archive uploaded: True" for line in record.read_text(encoding="utf-8").splitlines())


def run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True)


def push_record(root: Path, tag: str) -> None:
    paths = [
        f"release-records/{tag}.md",
        f"release-records/{tag}.json",
        "release-records/index.json",
    ]
    changed = subprocess.run(["git", "diff", "--quiet", "--", *paths], cwd=root).returncode != 0
    if not changed:
        return
    run_git(root, "add", "--", *paths)
    run_git(root, "commit", "-m", f"Publish {tag} Internet Archive mirror")
    run_git(root, "push")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish all incomplete release-plan packages to Internet Archive.")
    parser.add_argument("--credentials-file", type=Path, help="Private IA credentials file outside the repository.")
    parser.add_argument("--tag", action="append", dest="tags", help="Only publish this tag; repeat to select several.")
    parser.add_argument("--limit", type=int, help="Publish at most this many incomplete packages.")
    parser.add_argument("--retries", type=int, default=10, help="Retries for each failed file, default: %(default)s")
    parser.add_argument("--direct", action="store_true", help="Bypass HTTP(S) proxy variables for Internet Archive requests.")
    parser.add_argument("--delay-seconds", type=int, default=20, help="Pause between completed packages, default: %(default)s")
    parser.add_argument("--push", action="store_true", help="Commit and push each completed package record before continuing.")
    parser.add_argument("--dry-run", action="store_true", help="List incomplete planned packages without uploading.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if args.delay_seconds < 0 or args.retries < 0:
        parser.error("--delay-seconds and --retries must be non-negative")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    plan = load_plan(root)
    requested = set(args.tags or [])
    known_tags = {entry["tag"] for entry in plan}
    unknown_tags = requested - known_tags
    if unknown_tags:
        raise SystemExit(f"Unknown release-plan tags: {', '.join(sorted(unknown_tags))}")
    pending = [entry for entry in plan if (not requested or entry["tag"] in requested) and not archive_uploaded(root, entry["tag"])]
    if args.limit is not None:
        pending = pending[: args.limit]

    print(f"Planned packages: {len(plan)}; Internet Archive incomplete: {len(pending)}")
    for entry in pending:
        print(f"- {entry['tag']}: {entry['folder']}")
    if args.dry_run:
        return 0

    if args.push:
        run_git(root, "push")
    uploader = root / "release-tools" / "publish_to_internet_archive.py"
    for index, entry in enumerate(pending, start=1):
        command = [sys.executable, "-u", str(uploader), "--tag", entry["tag"], "--retries", str(args.retries)]
        if args.direct:
            command.append("--direct")
        if args.credentials_file is not None:
            command.extend(["--credentials-file", str(args.credentials_file)])
        print(f"\n[{index}/{len(pending)}] Publishing {entry['tag']}", flush=True)
        subprocess.run(command, cwd=root, check=True)
        if args.push:
            push_record(root, entry["tag"])
        if index < len(pending) and args.delay_seconds:
            print(f"Waiting {args.delay_seconds}s before the next package.", flush=True)
            time.sleep(args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
