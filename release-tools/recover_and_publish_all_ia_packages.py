#!/usr/bin/env python3
"""Sequentially recover public GitHub files and publish IA direct-file mirrors."""

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
    payload = json.loads(path.read_text(encoding="utf-8"))
    resources = payload.get("resources")
    if not isinstance(resources, list):
        raise SystemExit(f"Invalid release plan: {path}")
    result: list[dict[str, str]] = []
    for entry in resources:
        if not isinstance(entry, dict) or not all(isinstance(entry.get(key), str) for key in ("tag", "folder", "title")):
            raise SystemExit(f"Invalid release plan entry: {entry!r}")
        result.append(entry)
    return result


def direct_files_confirmed(root: Path, tag: str) -> bool:
    record = root / "release-records" / f"{tag}.md"
    return record.is_file() and any(
        line == "- Internet Archive uploaded: True" for line in record.read_text(encoding="utf-8").splitlines()
    )


def push_record(root: Path, tag: str) -> None:
    paths = [f"release-records/{tag}.md", f"release-records/{tag}.json", "release-records/index.json"]
    changed = subprocess.run(["git", "diff", "--quiet", "--", *paths], cwd=root).returncode != 0
    if not changed:
        return
    subprocess.run(["git", "add", "--", *paths], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", f"Publish {tag} Internet Archive direct files"], cwd=root, check=True)
    subprocess.run(["git", "push"], cwd=root, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover and publish incomplete IA direct-file mirrors in sequence.")
    parser.add_argument("--staging-dir", type=Path, required=True, help="Directory outside the repository for temporary individual files.")
    parser.add_argument("--credentials-file", type=Path, required=True, help="Private IA credentials file outside the repository.")
    parser.add_argument("--tag", action="append", dest="tags", help="Only publish this tag; repeatable.")
    parser.add_argument("--limit", type=int, help="Publish at most this many incomplete packages.")
    parser.add_argument("--retries", type=int, default=5, help="Retries per download or upload, default: %(default)s")
    parser.add_argument(
        "--verify-wait-seconds",
        type=int,
        default=900,
        help="Maximum Archive metadata-ingestion wait after each package, default: %(default)s",
    )
    parser.add_argument(
        "--metadata-verification-attempts",
        type=int,
        default=8,
        help="Additional verification-only attempts after a completed upload awaits metadata, default: %(default)s",
    )
    parser.add_argument("--direct", action="store_true", help="Bypass HTTP(S) proxy variables for Internet Archive operations.")
    parser.add_argument("--delay-seconds", type=int, default=30, help="Pause between completed packages, default: %(default)s")
    parser.add_argument("--push", action="store_true", help="Commit and push each package after remote file verification.")
    parser.add_argument("--dry-run", action="store_true", help="List incomplete planned packages without downloading or uploading.")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if (
        args.retries < 0
        or args.delay_seconds < 0
        or args.verify_wait_seconds < 0
        or args.metadata_verification_attempts < 0
    ):
        parser.error("retry, delay, metadata wait, and verification attempt values must be non-negative")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    root = repository_root()
    plan = load_plan(root)
    requested = set(args.tags or [])
    known = {entry["tag"] for entry in plan}
    unknown = requested - known
    if unknown:
        raise SystemExit(f"Unknown release-plan tags: {', '.join(sorted(unknown))}")
    pending = [entry for entry in plan if (not requested or entry["tag"] in requested) and not direct_files_confirmed(root, entry["tag"])]
    if args.limit is not None:
        pending = pending[: args.limit]
    print(f"Planned packages: {len(plan)}; direct-file mirrors pending: {len(pending)}", flush=True)
    for entry in pending:
        print(f"- {entry['tag']}: {entry['folder']}", flush=True)
    if args.dry_run:
        return 0

    if args.push:
        subprocess.run(["git", "push"], cwd=root, check=True)
    recovery = root / "release-tools" / "recover_and_publish_ia_package.py"
    verifier = root / "release-tools" / "publish_to_internet_archive.py"
    for index, entry in enumerate(pending, start=1):
        command = [
            sys.executable,
            "-u",
            str(recovery),
            "--tag",
            entry["tag"],
            "--staging-dir",
            str(args.staging_dir),
            "--credentials-file",
            str(args.credentials_file),
            "--retries",
            str(args.retries),
            "--verify-wait-seconds",
            str(args.verify_wait_seconds),
        ]
        if args.direct:
            command.append("--direct")
        print(f"\n[{index}/{len(pending)}] Publishing {entry['tag']}", flush=True)
        result = subprocess.run(command, cwd=root).returncode
        if result == 2:
            verify_command = [
                sys.executable,
                "-u",
                str(verifier),
                "--tag",
                entry["tag"],
                "--source-folder",
                str(args.staging_dir / entry["tag"]),
                "--verify-only",
                "--verify-wait-seconds",
                str(args.verify_wait_seconds),
            ]
            if args.direct:
                verify_command.append("--direct")
            for verification_attempt in range(1, args.metadata_verification_attempts + 1):
                print(
                    f"Metadata is pending for {entry['tag']}; verification-only attempt "
                    f"{verification_attempt}/{args.metadata_verification_attempts}.",
                    flush=True,
                )
                if subprocess.run(verify_command, cwd=root).returncode == 0:
                    result = 0
                    break
                if verification_attempt < args.metadata_verification_attempts and args.delay_seconds:
                    print(f"Waiting {args.delay_seconds}s before the next metadata check.", flush=True)
                    time.sleep(args.delay_seconds)
        if result != 0:
            raise SystemExit(f"Publishing {entry['tag']} failed with exit code {result}")
        if args.push:
            push_record(root, entry["tag"])
        if index < len(pending) and args.delay_seconds:
            print(f"Waiting {args.delay_seconds}s before the next package.", flush=True)
            time.sleep(args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
