#!/usr/bin/env python3
"""Upload one planned resource package to Internet Archive.

Credentials are read only from IA_ACCESS_KEY and IA_SECRET_KEY, or from a
credentials JSON file outside this repository. The public release record keeps
only the stable identifier and public URLs.
"""

from __future__ import annotations

import argparse
import html
import http.client
import io
import json
import os
import re
import ssl
import subprocess
import sys
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener, urlopen


ARCHIVE_HOST = "s3.us.archive.org"
ARCHIVE_METADATA_URL = "https://archive.org/metadata/{identifier}"
IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,99}$")
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
UPLOAD_CHUNK_SIZE = 256 * 1024
MULTIPART_THRESHOLD_BYTES = 8 * 1024 * 1024
MULTIPART_PART_SIZE = 5 * 1024 * 1024
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


def resolve_package(
    root: Path,
    entry: dict[str, str],
    source_folder: Path | None = None,
) -> tuple[Path, list[Path], list[Path]]:
    folder = source_folder.expanduser().resolve() if source_folder is not None else (root / entry["folder"]).resolve()
    if source_folder is None:
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


def fetch_metadata_pycurl(identifier: str) -> dict[str, Any] | None:
    try:
        import io
        import pycurl
    except ImportError as exc:
        raise SystemExit(
            "The pycurl package is required for the default transport. "
            "Install it with `python -m pip install pycurl`, or choose another transport."
        ) from exc
    url = ARCHIVE_METADATA_URL.format(identifier=quote_component(identifier))
    for attempt in range(4):
        body = io.BytesIO()
        client = pycurl.Curl()
        try:
            client.setopt(pycurl.URL, url)
            client.setopt(pycurl.NOPROXY, "*")
            client.setopt(pycurl.CONNECTTIMEOUT, 30)
            client.setopt(pycurl.TIMEOUT, 60)
            client.setopt(pycurl.USERAGENT, "reciter-resources-ia-uploader/1")
            client.setopt(pycurl.WRITEDATA, body)
            client.perform()
            status = client.getinfo(pycurl.RESPONSE_CODE)
        except pycurl.error as exc:
            if attempt == 3:
                raise SystemExit(f"Internet Archive metadata request failed: {exc}") from exc
            delay = 5 * 2**attempt
            print(f"Internet Archive metadata request failed: {exc}; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            continue
        finally:
            client.close()
        if status == 404:
            return None
        if status in RETRYABLE_STATUS and attempt < 3:
            delay = 5 * 2**attempt
            print(f"Internet Archive metadata returned {status}; retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            continue
        if status >= 400:
            raise SystemExit(f"Internet Archive metadata request failed ({status})")
        try:
            return json.loads(body.getvalue().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit("Internet Archive metadata response was not valid JSON") from exc
    raise AssertionError("unreachable")


def fetch_metadata(identifier: str, direct: bool = False, transport: str = "pycurl") -> dict[str, Any] | None:
    if transport == "pycurl":
        return fetch_metadata_pycurl(identifier)
    request = Request(
        ARCHIVE_METADATA_URL.format(identifier=quote_component(identifier)),
        headers={
            "Connection": "close",
            "User-Agent": "reciter-resources-ia-uploader/1",
        },
    )
    try:
        opener = build_opener(ProxyHandler({})) if direct else None
        response_context = opener.open(request, timeout=30) if opener is not None else urlopen(request, timeout=30)
        with response_context as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            return None
        body = exc.read(300).decode("utf-8", errors="replace")
        raise SystemExit(f"Internet Archive metadata request failed ({exc.code}): {body}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Internet Archive metadata request failed: {exc}") from exc


def remote_sizes(identifier: str, direct: bool = False, transport: str = "pycurl") -> dict[str, int]:
    metadata = fetch_metadata(identifier, direct=direct, transport=transport)
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


def put_file_stdlib(*, identifier: str, path: Path, headers: dict[str, str], retries: int) -> None:
    target = f"/{quote_component(identifier)}/{quote_component(path.name)}"
    for attempt in range(retries + 1):
        connection = http.client.HTTPSConnection(ARCHIVE_HOST, timeout=120, context=ssl.create_default_context())
        try:
            connection.putrequest("PUT", target)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.putheader("Content-Length", str(path.stat().st_size))
            connection.putheader("Connection", "close")
            connection.putheader("User-Agent", "reciter-resources-ia-uploader/1")
            connection.endheaders()
            with path.open("rb") as source:
                while chunk := source.read(UPLOAD_CHUNK_SIZE):
                    connection.send(chunk)
            response = connection.getresponse()
            body = response.read(500).decode("utf-8", errors="replace")
            if 200 <= response.status < 300:
                return
            if response.status not in RETRYABLE_STATUS or attempt == retries:
                raise SystemExit(f"Upload failed for {path.name} ({response.status}): {body}")
            delay = min(120, 5 * 2**attempt)
            print(f"{path.name}: server returned {response.status}; retrying in {delay}s", file=sys.stderr)
        except (OSError, http.client.HTTPException) as exc:
            if attempt == retries:
                raise SystemExit(f"Upload failed for {path.name}: {exc}") from exc
            delay = min(120, 5 * 2**attempt)
            print(f"{path.name}: {exc}; retrying in {delay}s", file=sys.stderr)
        finally:
            connection.close()
        time.sleep(delay)


def open_official_item(identifier: str, direct: bool = False) -> Any:
    try:
        import internetarchive
    except ImportError as exc:
        raise SystemExit(
            "The internetarchive package is required for the default transport. "
            "Install it with `python -m pip install internetarchive`, or use --transport stdlib."
        ) from exc
    session = internetarchive.ArchiveSession()
    session.trust_env = not direct
    return internetarchive.get_item(identifier, archive_session=session)


def put_file_official(
    *,
    item: Any,
    path: Path,
    metadata: dict[str, str],
    headers: dict[str, str],
    access_key: str,
    secret_key: str,
    retries: int,
) -> None:
    try:
        responses = item.upload(
            [str(path)],
            metadata=metadata,
            headers=headers,
            access_key=access_key,
            secret_key=secret_key,
            queue_derive=False,
            retries=retries,
            retries_sleep=5,
            verbose=False,
        )
    except Exception as exc:
        raise SystemExit(f"Upload failed for {path.name}: {exc}") from exc
    failures = [response for response in responses if getattr(response, "status_code", 200) >= 300]
    if failures:
        status = getattr(failures[0], "status_code", "unknown")
        raise SystemExit(f"Upload failed for {path.name} ({status})")


def pycurl_request(
    *,
    url: str,
    method: str,
    headers: list[str],
    body: bytes,
) -> tuple[int, bytes, dict[str, str]]:
    """Perform one small IA S3 request without using the machine proxy."""
    try:
        import pycurl
    except ImportError as exc:
        raise SystemExit("The pycurl package is required for the default transport.") from exc
    response_body = io.BytesIO()
    response_headers: dict[str, str] = {}
    client = pycurl.Curl()

    def receive_header(raw: bytes) -> int:
        line = raw.decode("iso-8859-1").strip()
        if ":" in line:
            name, value = line.split(":", 1)
            response_headers[name.lower()] = value.strip()
        return len(raw)

    try:
        client.setopt(pycurl.URL, url)
        client.setopt(pycurl.NOPROXY, "*")
        client.setopt(pycurl.CUSTOMREQUEST, method)
        client.setopt(pycurl.CONNECTTIMEOUT, 30)
        client.setopt(pycurl.TIMEOUT, 180)
        client.setopt(pycurl.USERAGENT, "reciter-resources-ia-uploader/1")
        client.setopt(pycurl.HTTPHEADER, [*headers, "Connection: close", "Expect:"])
        client.setopt(pycurl.HEADERFUNCTION, receive_header)
        client.setopt(pycurl.WRITEDATA, response_body)
        if method == "PUT":
            client.setopt(pycurl.UPLOAD, 1)
            client.setopt(pycurl.INFILESIZE_LARGE, len(body))
            client.setopt(pycurl.READDATA, io.BytesIO(body))
        elif method == "POST":
            client.setopt(pycurl.POST, 1)
            client.setopt(pycurl.POSTFIELDS, body)
        client.perform()
        return client.getinfo(pycurl.RESPONSE_CODE), response_body.getvalue(), response_headers
    finally:
        client.close()


def pycurl_request_with_retries(
    *,
    label: str,
    url: str,
    method: str,
    headers: list[str],
    body: bytes,
    retries: int,
) -> tuple[bytes, dict[str, str]]:
    try:
        import pycurl
    except ImportError as exc:
        raise SystemExit("The pycurl package is required for the default transport.") from exc
    for attempt in range(retries + 1):
        try:
            status, response_body, response_headers = pycurl_request(
                url=url,
                method=method,
                headers=headers,
                body=body,
            )
            if 200 <= status < 300:
                return response_body, response_headers
            failure = f"server returned {status}"
            retryable = status in RETRYABLE_STATUS
        except pycurl.error as exc:
            failure = str(exc)
            retryable = True
        if not retryable or attempt == retries:
            raise SystemExit(f"Upload failed for {label}: {failure}")
        delay = min(120, 5 * 2**attempt)
        print(f"{label}: {failure}; retrying in {delay}s", file=sys.stderr)
        time.sleep(delay)
    raise AssertionError("unreachable")


def parse_multipart_upload_id(body: bytes, path: Path) -> str:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise SystemExit(f"Multipart initialization returned invalid XML for {path.name}") from exc
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "UploadId" and element.text:
            return element.text.strip()
    raise SystemExit(f"Multipart initialization did not return an upload id for {path.name}")


def put_file_pycurl_multipart(*, identifier: str, path: Path, headers: dict[str, str], retries: int) -> None:
    """Upload a large file as independently retryable IA S3 multipart pieces."""
    target = f"https://{ARCHIVE_HOST}/{quote_component(identifier)}/{quote_component(path.name)}"
    header_lines = [f"{name}: {value}" for name, value in headers.items()]
    start_body, _ = pycurl_request_with_retries(
        label=f"{path.name}: multipart initialization",
        url=f"{target}?uploads",
        method="POST",
        headers=header_lines,
        body=b"",
        retries=retries,
    )
    upload_id = parse_multipart_upload_id(start_body, path)
    part_headers = [
        line
        for line in header_lines
        if not line.lower().startswith("x-archive-meta")
        and not line.lower().startswith("x-amz-auto-make-bucket")
        and not line.lower().startswith("x-archive-size-hint")
    ]
    parts: list[tuple[int, str]] = []
    with path.open("rb") as source:
        part_number = 1
        while chunk := source.read(MULTIPART_PART_SIZE):
            encoded_upload_id = quote_component(upload_id)
            _, response_headers = pycurl_request_with_retries(
                label=f"{path.name}: part {part_number}",
                url=f"{target}?partNumber={part_number}&uploadId={encoded_upload_id}",
                method="PUT",
                headers=part_headers,
                body=chunk,
                retries=retries,
            )
            etag = response_headers.get("etag")
            if not etag:
                raise SystemExit(f"Multipart upload did not return an ETag for {path.name} part {part_number}")
            parts.append((part_number, etag))
            print(f"{path.name}: uploaded part {part_number}", flush=True)
            part_number += 1
    complete_body = "<CompleteMultipartUpload>" + "".join(
        f"<Part><PartNumber>{number}</PartNumber><ETag>{html.escape(etag)}</ETag></Part>"
        for number, etag in parts
    ) + "</CompleteMultipartUpload>"
    pycurl_request_with_retries(
        label=f"{path.name}: multipart completion",
        url=f"{target}?uploadId={quote_component(upload_id)}",
        method="POST",
        headers=[
            f"Authorization: {headers['Authorization']}",
            "Content-Type: application/xml",
        ],
        body=complete_body.encode("utf-8"),
        retries=retries,
    )


def put_file_pycurl(*, identifier: str, path: Path, headers: dict[str, str], retries: int) -> None:
    try:
        import pycurl
    except ImportError as exc:
        raise SystemExit(
            "The pycurl package is required for the default transport. "
            "Install it with `python -m pip install pycurl`, or choose another transport."
        ) from exc
    if path.stat().st_size > MULTIPART_THRESHOLD_BYTES:
        put_file_pycurl_multipart(identifier=identifier, path=path, headers=headers, retries=retries)
        return
    target = f"https://{ARCHIVE_HOST}/{quote_component(identifier)}/{quote_component(path.name)}"
    header_lines = [f"{name}: {value}" for name, value in headers.items()]
    for attempt in range(retries + 1):
        client = pycurl.Curl()
        try:
            client.setopt(pycurl.URL, target)
            client.setopt(pycurl.NOPROXY, "*")
            client.setopt(pycurl.UPLOAD, 1)
            client.setopt(pycurl.CUSTOMREQUEST, "PUT")
            client.setopt(pycurl.INFILESIZE_LARGE, path.stat().st_size)
            client.setopt(pycurl.CONNECTTIMEOUT, 30)
            client.setopt(pycurl.TIMEOUT, 900)
            client.setopt(pycurl.USERAGENT, "reciter-resources-ia-uploader/1")
            client.setopt(pycurl.HTTPHEADER, [*header_lines, "Connection: close", "Expect:"])
            client.setopt(pycurl.WRITEFUNCTION, lambda data: len(data))
            with path.open("rb") as source:
                client.setopt(pycurl.READDATA, source)
                client.perform()
            status = client.getinfo(pycurl.RESPONSE_CODE)
            if 200 <= status < 300:
                return
            if status not in RETRYABLE_STATUS or attempt == retries:
                raise SystemExit(f"Upload failed for {path.name} ({status})")
            delay = min(120, 5 * 2**attempt)
            print(f"{path.name}: server returned {status}; retrying in {delay}s", file=sys.stderr)
        except pycurl.error as exc:
            if attempt == retries:
                raise SystemExit(f"Upload failed for {path.name}: {exc}") from exc
            delay = min(120, 5 * 2**attempt)
            print(f"{path.name}: {exc}; retrying in {delay}s", file=sys.stderr)
        finally:
            client.close()
        time.sleep(delay)


def delete_file_pycurl(*, identifier: str, filename: str, access_key: str, secret_key: str, retries: int) -> None:
    """Delete one exact IA file through the same direct transport as uploads."""
    target = f"https://{ARCHIVE_HOST}/{quote_component(identifier)}/{quote_component(filename)}"
    pycurl_request_with_retries(
        label=f"Delete {identifier}/{filename}",
        url=target,
        method="DELETE",
        headers=[
            f"Authorization: LOW {access_key}:{secret_key}",
            "x-archive-cascade-delete: 0",
        ],
        body=b"",
        retries=retries,
    )


def update_record(root: Path, tag: str, identifier: str) -> None:
    update_record_metadata(
        root,
        tag,
        {
            "Internet Archive identifier": f"`{identifier}`",
            "Internet Archive item": item_url(identifier),
            "Internet Archive uploaded": "True",
        },
    )


def update_record_metadata(root: Path, tag: str, replacements: dict[str, str]) -> None:
    path = root / "release-records" / f"{tag}.md"
    if not path.is_file():
        raise SystemExit(f"Release record not found: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
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


def verify_files(identifier: str, audio: list[Path], direct: bool = False, transport: str = "pycurl") -> list[str]:
    sizes = remote_sizes(identifier, direct=direct, transport=transport)
    return [path.name for path in audio if sizes.get(path.name) != path.stat().st_size]


def wait_for_files(
    identifier: str,
    audio: list[Path],
    wait_seconds: int,
    poll_seconds: int,
    direct: bool = False,
    transport: str = "pycurl",
) -> list[str]:
    deadline = time.monotonic() + wait_seconds
    while True:
        missing = verify_files(identifier, audio, direct=direct, transport=transport)
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
    parser.add_argument(
        "--source-folder",
        type=Path,
        help="Explicit package directory outside the repository; it must contain only the planned MP3 and sidecar files.",
    )
    parser.add_argument("--credentials-file", type=Path, help="Private JSON credentials file outside the repository.")
    parser.add_argument(
        "--transport",
        choices=("pycurl", "internetarchive", "stdlib"),
        default="pycurl",
        help="Upload implementation, default: %(default)s",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Bypass HTTP(S) proxy environment variables for Internet Archive requests.",
    )
    parser.add_argument("--collection", default="opensource_audio", help="IA collection metadata, default: %(default)s")
    parser.add_argument("--creator", default="Reciter Resources", help="IA creator metadata, default: %(default)s")
    parser.add_argument("--retries", type=int, default=10, help="Retries per failed file, default: %(default)s")
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
    folder, audio, package_files = resolve_package(root, entry, args.source_folder)
    total_size = sum(path.stat().st_size for path in package_files)
    existing = remote_sizes(identifier, direct=args.direct, transport=args.transport)
    pending = package_files if args.force else [path for path in package_files if existing.get(path.name) != path.stat().st_size]

    print(f"Internet Archive item: {item_url(identifier)}")
    try:
        folder_label = folder.relative_to(root).as_posix()
    except ValueError:
        folder_label = str(folder)
    print(f"Package: {folder_label} ({len(audio)} MP3 + {len(package_files) - len(audio)} sidecars, {total_size / 1024 / 1024:.2f} MiB)")
    print(f"Remote files already matching: {len(package_files) - len(pending)}; pending: {len(pending)}")
    if args.dry_run:
        return 0

    if not args.verify_only:
        access_key, secret_key = load_credentials(args.credentials_file)
        metadata = {
            "collection": args.collection,
            "mediatype": "audio",
            "title": entry["title"],
            "creator": args.creator,
            "description": "Audio package for language-study playback; matching text sidecars are linked from the reciter-resources repository.",
        }
        metadata_headers = {
            "x-amz-auto-make-bucket": "1",
            "x-archive-size-hint": str(total_size),
            "x-archive-queue-derive": "0",
        }
        raw_metadata_headers = {
            **metadata_headers,
            "x-archive-meta01-collection": args.collection,
            "x-archive-meta-mediatype": "audio",
            "x-archive-meta-title": entry["title"],
            "x-archive-meta-creator": args.creator,
            "x-archive-meta-description": metadata["description"],
        }
        item = open_official_item(identifier, direct=args.direct) if args.transport == "internetarchive" else None
        for index, path in enumerate(pending, start=1):
            print(f"[{index}/{len(pending)}] Uploading {path.name} ({path.stat().st_size / 1024 / 1024:.2f} MiB)")
            headers = {**metadata_headers, "Content-Type": CONTENT_TYPES[path.suffix.lower()]}
            if args.transport == "pycurl":
                put_file_pycurl(
                    identifier=identifier,
                    path=path,
                    headers={
                        **raw_metadata_headers,
                        "Content-Type": CONTENT_TYPES[path.suffix.lower()],
                        "Authorization": f"LOW {access_key}:{secret_key}",
                    },
                    retries=args.retries,
                )
            elif item is not None:
                put_file_official(
                    item=item,
                    path=path,
                    metadata=metadata,
                    headers=headers,
                    access_key=access_key,
                    secret_key=secret_key,
                    retries=args.retries,
                )
            else:
                put_file_stdlib(
                    identifier=identifier,
                    path=path,
                    headers={**headers, "Authorization": f"LOW {access_key}:{secret_key}"},
                    retries=args.retries,
                )

    missing = wait_for_files(
        identifier,
        package_files,
        args.verify_wait_seconds,
        args.verify_poll_seconds,
        direct=args.direct,
        transport=args.transport,
    )
    if missing:
        print("Remote verification incomplete:", *missing, sep="\n", file=sys.stderr)
        return 2
    update_record(root, args.tag, identifier)
    generate_index(root)
    print(f"Verified {len(package_files)} files and updated release-records for {identifier}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
