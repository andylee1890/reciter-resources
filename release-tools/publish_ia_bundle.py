#!/usr/bin/env python3
"""Create and upload one complete resource-package ZIP to Internet Archive."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

import publish_to_internet_archive as ia


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Upload a complete package ZIP beside IA's per-file mirror.")
    parser.add_argument("--tag", required=True)
    parser.add_argument("--credentials-file", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True, help="Directory outside the repository.")
    parser.add_argument("--retries", type=int, default=10)
    args = parser.parse_args(argv)
    root = ia.repository_root()
    entry = ia.load_plan_entry(root, args.tag)
    _, _, files = ia.resolve_package(root, entry)
    artifact_dir = args.artifact_dir.expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    bundle = artifact_dir / f"{args.tag}.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    identifier = f"reciter-{args.tag}"
    remote = ia.remote_sizes(identifier)
    if remote.get(bundle.name) != bundle.stat().st_size:
        access_key, secret_key = ia.load_credentials(args.credentials_file)
        ia.put_file_pycurl(
            identifier=identifier,
            path=bundle,
            headers={
                "x-amz-auto-make-bucket": "1",
                "x-archive-queue-derive": "0",
                "x-archive-meta01-collection": "opensource_audio",
                "x-archive-meta-mediatype": "audio",
                "x-archive-meta-title": entry["title"],
                "Content-Type": "application/zip",
                "Authorization": f"LOW {access_key}:{secret_key}",
            },
            retries=args.retries,
        )
    missing = ia.wait_for_files(identifier, [bundle], 600, 15)
    if missing:
        raise SystemExit(f"Bundle verification incomplete: {bundle.name}")
    print(f"Verified bundle: {ia.item_url(identifier)} {bundle.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
