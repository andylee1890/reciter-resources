#!/usr/bin/env python3
"""Audit resource filenames before they are sent to public storage systems.

Source names remain readable and may contain Unicode.  Delivery systems receive
the stable ASCII asset names produced by ``publish_season_release.py``.  A
literal ``#`` is rejected in source names because it is a URL fragment marker
and GitHub CLI also treats it as an asset-label separator.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
from collections import defaultdict
from pathlib import Path


URL_RESERVED = re.compile(r"[%&+;=?]")


def load_publisher_module(root: Path):
    script_path = root / "release-tools" / "publish_season_release.py"
    specification = importlib.util.spec_from_file_location("publish_season_release", script_path)
    if specification is None or specification.loader is None:
        raise SystemExit(f"Cannot load publisher helpers: {script_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def collect_files(root: Path) -> list[Path]:
    return sorted((path for path in root.rglob("*") if path.is_file()), key=lambda path: str(path).casefold())


def audit(root: Path, publisher) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    release_names: dict[str, list[str]] = defaultdict(list)

    for path in collect_files(root):
        relative = path.relative_to(root).as_posix()
        if "#" in path.name:
            errors.append(f"# is not permitted in source basename: {relative}")
        if URL_RESERVED.search(path.name):
            warnings.append(f"URL-reserved character retained in legacy source basename: {relative}")

        # This is the public storage name used by Release staging. It remains
        # safe even when the source basename is a readable Unicode title.
        delivery_name = publisher.github_release_asset_name(relative)
        release_names[delivery_name.casefold()].append(relative)

    for delivery_name, sources in sorted(release_names.items()):
        if len(sources) > 1:
            errors.append(
                f"Delivery-name collision ({delivery_name}): " + ", ".join(sources)
            )

    return {
        "root": str(root),
        "filesScanned": sum(len(sources) for sources in release_names.values()),
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="resources", type=Path, help="Resource directory to scan.")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Print every error and warning.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat legacy URL-reserved characters as failures as well as # and collisions.",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    resource_root = args.root if args.root.is_absolute() else root / args.root
    resource_root = resource_root.resolve()
    if not resource_root.is_dir():
        raise SystemExit(f"Directory not found: {resource_root}")

    report = audit(resource_root, load_publisher_module(root))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Scanned: {report['filesScanned']} files")
        print(f"Errors: {len(report['errors'])}")
        print(f"Warnings: {len(report['warnings'])}")
        for item in report["errors"]:
            print(f"ERROR: {item}")
        if args.verbose:
            for item in report["warnings"]:
                print(f"WARNING: {item}")
        elif report["warnings"]:
            print("Use --verbose to list legacy warnings.")

    return 1 if report["errors"] or (args.strict and report["warnings"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
