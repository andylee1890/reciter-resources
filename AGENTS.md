# Agent Notes

This repository is a public static resource repository for reciter-style English learning assets.

## Responsibilities

- Keep the root `README.md` public-facing. It should explain what the repository is and how external users can reference resources.
- Keep operational details, CLI usage, release workflow, and maintainer notes under `release-tools/` or this file.
- `release-tools/` is part of the public Git repository. It may contain only
  reusable, documented, non-destructive repository workflows listed in its
  README. Do not put one-off migration, cleanup, scraping, poster-processing,
  recovery staging, or personal batch scripts there.
- Temporary or historical scripts belong under the ignored `bak/release-tools/`
  directory. A script must not be committed merely because it was useful once.
- Before committing, compare `git ls-files release-tools` with the public-tool
  allowlist in `release-tools/README.md`; unlisted scripts are not public assets.
- Keep release link indexes and takedown notes under `release-records/`.
- Keep versioned learning resources under `resources/`.

## Resource Rules

- Do not track audio binaries in Git. `.mp3` and other audio formats must remain ignored.
- Before committing, verify `git ls-files "*.mp3"` returns no files.
- Text assets such as `.srt`, `.lrc`, `.rec`, and `.recx` are code assets and may be committed.
- Audio and text sidecars should share the same basename, for example:

```text
The Office US S02E01 The Dundies.mp3
The Office US S02E01 The Dundies.srt
The Office US S02E01 The Dundies.rec
```

## Release Workflow

- Publish audio by folder or season through GitHub Releases; Internet Archive may be added as an independent mirror.
- Use the Python script in `release-tools/`; do not add OS-specific publish scripts.
- Keep temporary scripts out of the repository. For local-only work, use
  `bak/release-tools/` or another ignored workspace directory and remove private
  paths, credentials, browser/MCP details, and machine-specific assumptions from
  anything that is committed.
- Generated release records should include:
  - GitHub Release page.
  - GitHub Release asset URLs for audio.
  - GitHub Raw URLs for text sidecars.
  - jsDelivr URLs for text sidecars.
  - Internet Archive item and asset URLs when that mirror is uploaded.
- If a resource is withdrawn, update the relevant record instead of silently replacing links.

## Copyright And Attribution

- Do not claim official authorization, partnership, or ownership that the project does not have.
- For third-party open-source project ideas, record attribution clearly when reused.
- If a clear rights-holder takedown request appears, remove the affected resource links or assets at the appropriate granularity and document the action in `release-records/`.

## Editing Guidance

- Prefer small, explicit edits.
- Preserve the existing folder layout unless the user asks to reorganize it.
- Use cross-platform Python for repository automation.
- Do not move, delete, normalize, or rewrite user resource files without an explicit request.
