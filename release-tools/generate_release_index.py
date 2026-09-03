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
PART_RELEASE_TABLE_HEADER = (
    "| Audio | Size MiB | GitHub Release asset | Internet Archive file | GitHub Raw sidecars | jsDelivr sidecars |"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def poster_index_path(root: Path) -> Path:
    return root / "artwork" / "posters" / "index.json"


def course_sources_path(root: Path) -> Path:
    return root / "release-records" / "course-sources.json"


def course_detail_relative_path(tag: str) -> str:
    return f"courses/{tag}.json"


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
    metadata_section = True
    for index, line in enumerate(lines[1:], start=1):
        if line == "## Link Bases":
            metadata_section = False
        match = METADATA_PATTERN.match(line)
        if metadata_section and match:
            metadata[match.group("key")] = match.group("value")
        if line in (RELEASE_TABLE_HEADER, ARCHIVE_TABLE_HEADER, PART_RELEASE_TABLE_HEADER):
            table_start = index + 2
            break

    audio_delivery = metadata.get("Audio delivery", "githubRelease")
    if audio_delivery not in ("githubRelease", "githubReleaseParts", "internetArchive"):
        raise ValueError(f"{path}: unsupported audio delivery: {audio_delivery}")
    required_metadata = ("Tag", "Repo", "Branch", "Folder", "Created at", "Audio files", "Total size", "Dry run")
    if audio_delivery == "githubRelease":
        required_metadata += ("Release",)
    if audio_delivery == "githubReleaseParts":
        required_metadata += ("GitHub Release parts",)
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
        expected_cells = 6 if audio_delivery == "githubReleaseParts" else 5
        if len(cells) != expected_cells:
            raise ValueError(f"{path}: malformed files table row")
        primary_links = parse_links(cells[2])
        if "mp3" not in primary_links:
            raise ValueError(f"{path}: missing mp3 link for {cells[0]}")
        archive_links = parse_links(cells[3]) if audio_delivery == "githubReleaseParts" else {}
        sidecar_offset = 4 if audio_delivery == "githubReleaseParts" else 3
        audio.append(
            {
                "name": cells[0].replace(r"\|", "|"),
                "sizeMiB": float(cells[1]),
                "audioUrl": primary_links["mp3"],
                "archiveAudioUrl": archive_links.get("mp3"),
                "sidecars": {
                    "githubRaw": parse_links(cells[sidecar_offset]),
                    "jsDelivr": parse_links(cells[sidecar_offset + 1]),
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
            "recxUploaded": metadata.get("Internet Archive RECX uploaded", "False").lower(),
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
        "releaseUrls": [
            url.strip() for url in metadata.get("GitHub Release parts", "").split(",") if url.strip()
        ],
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
                **{key: value for key, value in archive.items() if key not in ("directFiles", "recxUploaded")},
            }
        ]
        if archive is not None
        else []
    )
    if record["audioDelivery"] == "githubRelease":
        return {"githubRelease": {"releaseUrl": record["releaseUrl"]}, "mirrors": mirrors}
    if record["audioDelivery"] == "githubReleaseParts":
        return {"githubRelease": {"releaseUrls": record["releaseUrls"]}, "mirrors": mirrors}
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
                    if record["audioDelivery"] in ("githubRelease", "githubReleaseParts")
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
                                if extension != "recx" or archive.get("recxUploaded") == "true"
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
    records: list[dict[str, Any]],
    posters: list[dict[str, Any]],
    generated_at: str,
    posters_by_tag: dict[str, dict[str, Any]],
    courses: list[dict[str, Any]],
) -> dict[str, Any]:
    repositories = {record["repository"] for record in records}
    return {
        "schemaVersion": 5,
        "generatedAt": generated_at,
        "repository": repositories.pop() if len(repositories) == 1 else None,
        "posterIndex": poster_index_reference(records),
        "posters": posters,
        "courses": course_summaries(courses),
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


def published_courses(root: Path) -> list[dict[str, Any]]:
    source_path = course_sources_path(root)
    if not source_path.is_file():
        return []

    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("schemaVersion") != 1:
        raise ValueError(f"{source_path}: unsupported schema version")
    repository = source.get("repository")
    branch = source.get("branch")
    items = source.get("courses")
    if not isinstance(repository, str) or not isinstance(branch, str) or not isinstance(items, list):
        raise ValueError(f"{source_path}: repository, branch, and courses are required")

    courses: list[dict[str, Any]] = []
    seen_tags: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{source_path}: course entry must be an object")
        tag = item.get("tag")
        title = item.get("title")
        folder = item.get("folder")
        if not isinstance(tag, str) or not isinstance(title, str) or not isinstance(folder, str):
            raise ValueError(f"{source_path}: course tag, title, and folder are required")
        if tag in seen_tags:
            raise ValueError(f"{source_path}: duplicate course tag: {tag}")
        seen_tags.add(tag)

        folder_path = (root / folder).resolve()
        try:
            folder_path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"{source_path}: course folder escapes repository: {folder}") from exc
        if not folder_path.is_dir():
            raise ValueError(f"{source_path}: course folder not found: {folder}")

        srt_files = sorted(path for path in folder_path.iterdir() if path.is_file() and path.suffix.lower() == ".srt")
        if not srt_files:
            raise ValueError(f"{source_path}: no SRT files found in {folder}")
        courses.append(
            {
                "tag": tag,
                "title": title,
                "folder": folder,
                "repository": repository,
                "branch": branch,
                "srtFiles": srt_files,
            }
        )
    return courses


def course_detail(course: dict[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "tag": course["tag"],
        "title": course["title"],
        "folder": course["folder"],
        "srtCount": len(course["srtFiles"]),
        "srt": [
            {
                "name": path.name,
                **poster_urls(
                    course["repository"],
                    course["branch"],
                    f"{course['folder']}/{path.name}",
                ),
            }
            for path in course["srtFiles"]
        ],
    }


def course_summaries(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tag": course["tag"],
            "title": course["title"],
            "srtCount": len(course["srtFiles"]),
            "detailFile": f"release-records/{course_detail_relative_path(course['tag'])}",
            "detailRaw": poster_urls(
                course["repository"], course["branch"], f"release-records/{course_detail_relative_path(course['tag'])}"
            )["githubRaw"],
            "detailJsDelivr": poster_urls(
                course["repository"], course["branch"], f"release-records/{course_detail_relative_path(course['tag'])}"
            )["jsDelivr"],
        }
        for course in courses
    ]


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
    if source.get("schemaVersion") != 1:
        raise ValueError(f"{path}: unsupported poster source index")

    # The public poster index is also the durable source now. Accept the old
    # local `items` shape for compatibility with older working copies.
    source_items = source.get("items", source.get("posters"))
    if not isinstance(source_items, list):
        raise ValueError(f"{path}: poster list is missing")

    tags = {record["tag"] for record in records}
    linked: dict[str, dict[str, Any]] = {}
    public_items: list[dict[str, Any]] = []
    for item in source_items:
        item_tags = item.get("usedBy")
        card = item.get("card")
        if item_tags == [] or item_tags is None:
            continue
        if isinstance(item_tags, str):
            item_tags = [item_tags]
        if not isinstance(item_tags, list) or len(item_tags) != 1:
            raise ValueError(f"{path}: poster {item.get('id')} must reference exactly one release")
        if not isinstance(card, dict):
            raise ValueError(f"{path}: poster {item.get('id')} has no generated card")
        tag = item_tags[0]
        if tag not in tags:
            # The artwork source may include prepared posters for a future
            # release. They are not part of the published-resource index yet.
            continue
        if tag in linked:
            raise ValueError(f"{path}: release {tag} has multiple posters")
        record = next(record for record in records if record["tag"] == tag)
        original = item.get("original", {})
        original_path = original.get("path") or f"artwork/posters/{item.get('file', '')}"
        card_path = card.get("path") or f"artwork/posters/{card.get('file', '')}"
        if not original_path or not card_path or original_path.endswith("/") or card_path.endswith("/"):
            raise ValueError(f"{path}: poster {item.get('id')} has invalid asset paths")
        asset = {
            "id": item["id"],
            "kind": item["kind"],
            "sourceType": item["sourceType"],
            "original": poster_urls(record["repository"], record["branch"], original_path),
            "card": {
                **poster_urls(record["repository"], record["branch"], card_path),
                **{
                    key: value
                    for key, value in card.items()
                    if key not in {"file", "path", "githubRaw", "jsDelivr"}
                },
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
    if target.is_file():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = None
        if isinstance(existing, dict) and all(
            existing.get(key) == payload[key] for key in ("schemaVersion", "repository", "posterIndex", "posters")
        ):
            return
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
    courses = published_courses(root)
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
    for course in courses:
        detail_path = root / "release-records" / course_detail_relative_path(course["tag"])
        detail_path.parent.mkdir(parents=True, exist_ok=True)
        detail_path.write_text(
            json.dumps(
                course_detail(course, existing_generated_at(detail_path, generated_at)), ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )

    index = master_index(records, posters, generated_at, posters_by_tag, courses)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {len(records)} published releases to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
