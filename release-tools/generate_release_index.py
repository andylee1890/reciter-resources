#!/usr/bin/env python3
"""Generate a machine-readable index from published release records."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote


METADATA_PATTERN = re.compile(r"^- (?P<key>[^:]+): (?P<value>.*)$")
LINK_PATTERN = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
RELEASE_TABLE_HEADER = "| Audio | Size MiB | Release asset | GitHub Raw sidecars | jsDelivr sidecars |"
ARCHIVE_TABLE_HEADER = "| Audio | Size MiB | Internet Archive file | GitHub Raw sidecars | jsDelivr sidecars |"


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def poster_index_path(root: Path) -> Path:
    return root / "artwork" / "posters" / "index.local.json"


def parse_links(cell: str) -> dict[str, str]:
    return {label.lstrip("."): url for label, url in LINK_PATTERN.findall(cell)}


def quote_path(value: str) -> str:
    return quote(value, safe="/")


def quote_filename(value: str) -> str:
    return quote(value, safe="")


def archive_item_url(identifier: str) -> str:
    return f"https://archive.org/details/{quote_path(identifier)}"


def archive_download_url(identifier: str, filename: str) -> str:
    return f"https://archive.org/download/{quote_path(identifier)}/{quote_filename(filename)}"


def parse_record(path: Path) -> dict[str, Any] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError(f"{path}: missing title")

    metadata: dict[str, str] = {}
    table_start: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        match = METADATA_PATTERN.match(line)
        if match:
            metadata[match.group("key")] = match.group("value")
        if line in (RELEASE_TABLE_HEADER, ARCHIVE_TABLE_HEADER):
            table_start = index + 2
            break

    audio_delivery = metadata.get("Audio delivery", "githubRelease")
    if audio_delivery not in ("githubRelease", "internetArchive"):
        raise ValueError(f"{path}: unsupported audio delivery: {audio_delivery}")
    required_metadata = ("Tag", "Repo", "Branch", "Folder", "Created at", "Audio files", "Total size", "Dry run")
    if audio_delivery == "githubRelease":
        required_metadata += ("Release",)
    missing = [key for key in required_metadata if key not in metadata]
    if missing:
        raise ValueError(f"{path}: missing metadata: {', '.join(missing)}")
    if metadata.get("Published", "False").lower() != "true":
        return None
    if table_start is None:
        raise ValueError(f"{path}: missing files table")

    audio: list[dict[str, Any]] = []
    for line in lines[table_start:]:
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise ValueError(f"{path}: malformed files table row")
        asset_links = parse_links(cells[2])
        if "mp3" not in asset_links:
            raise ValueError(f"{path}: missing mp3 link for {cells[0]}")
        audio.append(
            {
                "name": cells[0].replace(r"\|", "|"),
                "sizeMiB": float(cells[1]),
                "audioUrl": asset_links["mp3"],
                "sidecars": {
                    "githubRaw": parse_links(cells[3]),
                    "jsDelivr": parse_links(cells[4]),
                },
            }
        )

    expected_count = int(metadata["Audio files"])
    if len(audio) != expected_count:
        raise ValueError(f"{path}: expected {expected_count} audio rows, found {len(audio)}")

    total_size_match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?) MiB", metadata["Total size"])
    if total_size_match is None:
        raise ValueError(f"{path}: invalid total size")

    archive_uploaded = metadata.get("Internet Archive uploaded", "False").lower() == "true"
    archive_identifier = metadata.get("Internet Archive identifier", "").strip("`")
    if archive_uploaded and not archive_identifier:
        raise ValueError(f"{path}: Internet Archive is marked uploaded but has no identifier")
    archive: dict[str, str] | None = None
    if archive_uploaded:
        archive = {
            "identifier": archive_identifier,
            "itemUrl": metadata.get("Internet Archive item", archive_item_url(archive_identifier)),
            "directFiles": "true",
        }
    return {
        "tag": metadata["Tag"].strip("`"),
        "title": lines[0][2:],
        "repository": metadata["Repo"].strip("`"),
        "branch": metadata["Branch"].strip("`"),
        "folder": metadata["Folder"].strip("`"),
        "createdAt": metadata["Created at"],
        "audioDelivery": audio_delivery,
        "releaseUrl": metadata.get("Release"),
        "audioCount": expected_count,
        "totalSizeMiB": float(total_size_match.group(1)),
        "audio": audio,
        "internetArchive": archive,
    }


def published_records(records_dir: Path) -> list[dict[str, Any]]:
    releases: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for path in sorted(records_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        record = parse_record(path)
        if record is None:
            continue
        if record["tag"] in seen_tags:
            raise ValueError(f"Duplicate published release tag: {record['tag']}")
        seen_tags.add(record["tag"])
        releases.append(record)

    return releases


def platforms_for(record: dict[str, Any]) -> dict[str, Any]:
    archive = record["internetArchive"]
    mirrors = (
        [
            {
                "provider": "internetArchive",
                **{key: value for key, value in archive.items() if key != "directFiles"},
            }
        ]
        if archive is not None
        else []
    )
    if record["audioDelivery"] == "githubRelease":
        return {"githubRelease": {"releaseUrl": record["releaseUrl"]}, "mirrors": mirrors}
    return {"mirrors": mirrors}


def release_detail(record: dict[str, Any], generated_at: str, poster: dict[str, Any]) -> dict[str, Any]:
    archive = record["internetArchive"]
    archive_has_direct_files = archive is not None and archive.get("directFiles") == "true"

    def track_mirrors(track: dict[str, Any]) -> list[dict[str, str]]:
        if archive is None:
            return []
        mirrors: list[dict[str, str]] = []
        if archive_has_direct_files:
            mirrors.append(
                {
                    "provider": "internetArchive",
                    "url": archive_download_url(archive["identifier"], track["name"]),
                }
            )
        return mirrors

    def archive_sidecar_filename(track: dict[str, Any], key: str) -> str:
        stem = Path(track["name"]).stem
        if key == "srtZh":
            return f"{stem}_zh.srt"
        return f"{stem}.{key}"

    return {
        "schemaVersion": 5,
        "generatedAt": generated_at,
        "tag": record["tag"],
        "title": record["title"],
        "repository": record["repository"],
        "branch": record["branch"],
        "folder": record["folder"],
        "createdAt": record["createdAt"],
        "poster": poster,
        "platforms": platforms_for(record),
        "audioCount": record["audioCount"],
        "totalSizeMiB": record["totalSizeMiB"],
        "audio": [
            {
                "name": track["name"],
                "sizeMiB": track["sizeMiB"],
                "audio": (
                    {"githubRelease": track["audioUrl"], "mirrors": track_mirrors(track)}
                    if record["audioDelivery"] == "githubRelease"
                    else {"mirrors": track_mirrors(track)}
                ),
                "sidecars": {
                    **track["sidecars"],
                    **(
                        {
                            "internetArchive": {
                                extension: archive_download_url(
                                    archive["identifier"],
                                    archive_sidecar_filename(track, extension),
                                )
                                for extension in track["sidecars"]["githubRaw"]
                            }
                        }
                        if archive_has_direct_files
                        else {}
                    ),
                },
            }
            for track in record["audio"]
        ],
    }


def master_index(
    records: list[dict[str, Any]], generated_at: str, posters_by_tag: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    repositories = {record["repository"] for record in records}
    return {
        "schemaVersion": 5,
        "generatedAt": generated_at,
        "repository": repositories.pop() if len(repositories) == 1 else None,
        "posterIndex": poster_index_reference(records),
        "releases": [
            {
                "tag": record["tag"],
                "title": record["title"],
                "createdAt": record["createdAt"],
                "audioCount": record["audioCount"],
                "totalSizeMiB": record["totalSizeMiB"],
                "detailFile": f"{record['tag']}.json",
                "detailRaw": (
                    f"https://raw.githubusercontent.com/{record['repository']}/"
                    f"{record['branch']}/release-records/{record['tag']}.json"
                ),
                "poster": posters_by_tag[record["tag"]],
                "platforms": platforms_for(record),
                **(
                    {"releaseUrl": record["releaseUrl"]}
                    if record["audioDelivery"] == "githubRelease"
                    else {}
                ),
            }
            for record in records
        ],
    }


def poster_urls(repository: str, branch: str, path: str) -> dict[str, str]:
    quoted_path = quote_path(path)
    return {
        "path": path,
        "githubRaw": f"https://raw.githubusercontent.com/{repository}/{branch}/{quoted_path}",
        "jsDelivr": f"https://cdn.jsdelivr.net/gh/{repository}@{branch}/{quoted_path}",
    }


def poster_index_reference(records: list[dict[str, Any]]) -> dict[str, str]:
    repositories = {record["repository"] for record in records}
    branches = {record["branch"] for record in records}
    if len(repositories) != 1 or len(branches) != 1:
        raise ValueError("Cannot create a single poster index reference for multiple repositories or branches")
    return poster_urls(repositories.pop(), branches.pop(), "artwork/posters/index.json")


def published_posters(records: list[dict[str, Any]], root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    path = poster_index_path(root)
    if not path.is_file():
        raise ValueError(f"Poster source index not found: {path}")
    source = json.loads(path.read_text(encoding="utf-8"))
    if source.get("schemaVersion") != 1 or not isinstance(source.get("items"), list):
        raise ValueError(f"{path}: unsupported poster source index")

    tags = {record["tag"] for record in records}
    linked: dict[str, dict[str, Any]] = {}
    public_items: list[dict[str, Any]] = []
    for item in source["items"]:
        item_tags = item.get("usedBy")
        card = item.get("card")
        if item_tags == []:
            continue
        if not isinstance(item_tags, list) or len(item_tags) != 1:
            raise ValueError(f"{path}: poster {item.get('id')} must reference exactly one release")
        if not isinstance(card, dict) or not isinstance(card.get("file"), str):
            raise ValueError(f"{path}: poster {item.get('id')} has no generated card")
        tag = item_tags[0]
        if tag not in tags:
            raise ValueError(f"{path}: poster {item.get('id')} references unknown release {tag}")
        if tag in linked:
            raise ValueError(f"{path}: release {tag} has multiple posters")
        record = next(record for record in records if record["tag"] == tag)
        asset = {
            "id": item["id"],
            "kind": item["kind"],
            "sourceType": item["sourceType"],
            "original": poster_urls(record["repository"], record["branch"], f"artwork/posters/{item['file']}"),
            "card": {
                **poster_urls(record["repository"], record["branch"], f"artwork/posters/{card['file']}"),
                **{key: value for key, value in card.items() if key != "file"},
            },
        }
        for key in ("source", "sourceImage"):
            if key in item:
                asset[key] = item[key]
        linked[tag] = asset
        public_items.append({**asset, "usedBy": tag})

    missing = sorted(tags - linked.keys())
    if missing:
        raise ValueError(f"Missing posters for published releases: {', '.join(missing)}")
    return public_items, linked


def write_poster_index(
    records: list[dict[str, Any]], posters: list[dict[str, Any]], generated_at: str, root: Path
) -> None:
    reference = poster_index_reference(records)
    target = root / reference["path"]
    payload = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "repository": records[0]["repository"],
        "posterIndex": reference,
        "posters": posters,
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def existing_generated_at(path: Path, fallback: str) -> str:
    """Keep a published detail record's original generation timestamp stable."""
    if not path.is_file():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback
    return value.get("generatedAt") if isinstance(value.get("generatedAt"), str) else fallback


def parse_args() -> argparse.Namespace:
    root = repository_root()
    parser = argparse.ArgumentParser(description="Generate release-records/index.json from published release records.")
    parser.add_argument("--records-dir", type=Path, default=root / "release-records")
    parser.add_argument("--output", type=Path, default=root / "release-records" / "index.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    records_dir = args.records_dir.resolve()
    output_path = args.output.resolve()
    if not records_dir.is_dir():
        raise SystemExit(f"Records directory not found: {records_dir}")

    records = published_records(records_dir)
    root = repository_root()
    generated_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    posters, posters_by_tag = published_posters(records, root)
    write_poster_index(records, posters, generated_at, root)
    for record in records:
        detail_path = records_dir / f"{record['tag']}.json"
        detail_path.write_text(
            json.dumps(
                release_detail(record, existing_generated_at(detail_path, generated_at), posters_by_tag[record["tag"]]),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    index = master_index(records, generated_at, posters_by_tag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(records)} published releases to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
