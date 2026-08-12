# Poster Assets

`artwork/posters/` contains public, card-oriented visual assets for the resource
catalog. It is separate from `resources/`: subtitles and REC files remain
learning sidecars, while posters are catalog presentation assets.

Use [index.json](index.json) to map a course or release tag to its poster. The
directory is intentionally series-oriented: one poster is reused by all seasons
of the same show instead of storing duplicate images per release.

All files are WebP and are sized for responsive card rendering. Do not infer
that a third-party catalog image is official artwork or that the repository owns
it. Each item records its source page and source type in `index.json`.

Stable public URLs:

- GitHub Raw: `https://raw.githubusercontent.com/andylee1890/reciter-resources/main/artwork/posters/...`
- jsDelivr: `https://cdn.jsdelivr.net/gh/andylee1890/reciter-resources@main/artwork/posters/...`

The `site-course-card` entries are original catalog artwork. The `textbook-cover`
and `series-poster` entries are source-derived reference images and should be
replaced or removed at the relevant item level if a rights-holder asks.
