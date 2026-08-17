#!/usr/bin/env python3
"""Regenerate local records for the new Cambridge IELTS and TOEFL releases."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


NEW_TAG_PREFIXES = ("cambridge-ielts-", "toefl-listening-")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    root = repository_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=root / "release-tools" / "release-plan.json")
    parser.add_argument("--repo", default="andylee1890/reciter-resources")
    parser.add_argument("--branch", default="main")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    publish_script = repository_root() / "release-tools" / "publish_season_release.py"
    resources = [
        item
        for item in plan.get("resources", [])
        if str(item.get("tag", "")).startswith(NEW_TAG_PREFIXES)
    ]
    if len(resources) != 19:
        raise SystemExit(f"Expected 19 new resources in the release plan, found {len(resources)}")

    for item in resources:
        command = [
            sys.executable,
            str(publish_script),
            "--folder",
            item["folder"],
            "--tag",
            item["tag"],
            "--title",
            item["title"],
            "--repo",
            args.repo,
            "--branch",
            args.branch,
            "--record-only",
        ]
        subprocess.run(command, cwd=repository_root(), check=True)
    print(f"Regenerated {len(resources)} local release records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
