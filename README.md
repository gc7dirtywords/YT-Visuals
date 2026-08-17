# YT Visuals

Local system for cataloging and sourcing reusable images and video clips used in
YouTube production. It includes the SQLite catalog, a recursive local-library scanner,
basic catalog search, and a provider-neutral acquisition layer with Pexels as the first
provider.

The project does not yet support Pixabay, generate manifests, use AI services, automate
DaVinci Resolve, or assemble video.

## Existing media layout

- `Library/Images` stores downloaded or curated images.
- `Library/Videos` stores downloaded or curated video clips.
- `Projects` stores episode/project working material.
- `Temp` is disposable working space.
- `Tools` is reserved for project-local helper tools.
- `Data/catalog.sqlite3` is the generated local catalog database.

Media paths saved in the catalog are relative to this repository root. The database,
media library, temporary files, virtual environment, and local `.env` file are ignored
by Git.

## Setup

Python 3.11 is supported. From PowerShell in this directory:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

No `.env` file is loaded by the application. `YT_VISUALS_ROOT` may be set as an
environment variable if commands need to operate on a different compatible root.

## Provider architecture

Provider integrations implement the common interface in `yt_visuals.providers.base`.
Calling code receives `MediaSearchResult` and `SearchPage` domain objects rather than
provider response dictionaries. Each normalized result includes provider and asset IDs,
media type, creator and source links, download and preview links, dimensions, duration,
MIME type, license and suggested attribution, and the raw provider metadata.

Pexels-specific endpoints, response validation, and error mapping live only in
`yt_visuals.providers.pexels`. A future Pixabay provider can implement the same interface
without changing the acquisition service or CLI workflow.

Search does not write to the database or download anything. Acquisition is always an
explicit command.

## Pexels setup

Request an API key from the [Pexels API page](https://www.pexels.com/api/) and set it in
the current PowerShell session:

```powershell
$env:PEXELS_API_KEY = "your-key-here"
```

Do not place the key in source-controlled files. The application reads only the
`PEXELS_API_KEY` environment variable. The provider-list command works without a key and
shows whether Pexels is configured:

```powershell
.\.venv\Scripts\yt-visuals.exe providers
.\.venv\Scripts\yt-visuals.exe providers --json
```

## Commands

Create the database and apply all pending migrations:

```powershell
.\.venv\Scripts\yt-visuals.exe db upgrade
```

Run the complete environment check. This also initializes or migrates the database:

```powershell
.\.venv\Scripts\yt-visuals.exe doctor
```

## Local library scanner

The scanner recursively inspects supported files below `Library/Images` (JPEG, PNG, and
WebP) and `Library/Videos` (MP4, MOV, M4V, MKV, and WebM). Images are validated and sized
with Pillow. Videos are inspected with ffprobe for dimensions, duration, and useful probe
metadata. Every cataloged file has a root-relative path, size, modified time, MIME type,
SHA-256, dimensions, and duration where applicable.

Preview a reconciliation without changing the database, then perform it:

```powershell
.\.venv\Scripts\yt-visuals.exe library scan --dry-run
.\.venv\Scripts\yt-visuals.exe library scan
.\.venv\Scripts\yt-visuals.exe library scan --verbose
.\.venv\Scripts\yt-visuals.exe library scan --json
```

Normal output is a compact summary; `--verbose` includes per-file decisions. A corrupt,
unreadable, disappearing, or unprobeable file is reported as an inspection error without
stopping other files from being cataloged. Symlinks are not followed, so scanning cannot
escape the two configured library roots.

Scanning is read-only with respect to media bytes: it never moves, renames, overwrites,
transcodes, or deletes user files. Unsupported extensions are ignored. SHA-256 is the
authoritative physical identity, while an exact path/size/modified-time match avoids
rehashing unchanged files on later scans.

### Local paths, duplicates, and missing media

`media_locations` records local availability independently from provider provenance. One
`media_assets` row can therefore retain multiple paths for byte-identical copies. The
first available path remains the asset's canonical path. If the last available copy is
renamed or moved inside the library, a matching SHA-256 associates the new path with the
same asset and updates the canonical path without losing tags, sources, license details,
or usage history. Old paths remain recorded as missing rather than being silently erased.

If all known paths disappear, the asset is marked `missing`; the catalog row and all its
history and provenance remain intact. A later scan automatically restores an identical
path when the file reappears. Use the status command to see current availability:

```powershell
.\.venv\Scripts\yt-visuals.exe library status
.\.venv\Scripts\yt-visuals.exe library status --json
```

Local files receive `local_import` location provenance and no invented provider, creator,
license, or attribution. New provider downloads receive `provider_download` location
provenance plus their independent `media_sources` and `asset_licenses` records. If a
provider download matches a pre-existing local SHA-256, the existing asset is reused and
the provider source is attached; local and provider provenance are both preserved.

## Local catalog search

Catalog search never scans, downloads, or creates usage records. It matches paths and
filenames, titles/descriptions, tags, providers, creators, MIME types, and project/story
usage text. Results expose availability, dimensions, derived orientation, duration,
SHA-256, usage count, and last-used time. Examples:

```powershell
.\.venv\Scripts\yt-visuals.exe library search "factory"
.\.venv\Scripts\yt-visuals.exe library search --type image --orientation landscape --unused
.\.venv\Scripts\yt-visuals.exe library search --type video --min-duration 5 --max-duration 30
.\.venv\Scripts\yt-visuals.exe library search --provider pexels
.\.venv\Scripts\yt-visuals.exe library search --missing --json
```

Additional filters include `--mime`, `--min-width`, `--min-height`, `--used`, and
`--limit`. Search shows active assets by default; `--missing` selects missing assets.

Search Pexels without downloading or changing the catalog:

```powershell
.\.venv\Scripts\yt-visuals.exe search pexels photos "abandoned factory"
.\.venv\Scripts\yt-visuals.exe search pexels photos "desert road" --orientation landscape --size large --color gray --page 2 --per-page 20
.\.venv\Scripts\yt-visuals.exe search pexels videos "storm clouds" --orientation landscape --size medium
.\.venv\Scripts\yt-visuals.exe search pexels photos "city skyline" --json
```

Download and catalog one selected result explicitly:

```powershell
.\.venv\Scripts\yt-visuals.exe download pexels photos 2014422
.\.venv\Scripts\yt-visuals.exe download pexels videos 2499611
.\.venv\Scripts\yt-visuals.exe download pexels photos 2014422 --json
```

Photo downloads use Pexels' original image URL. When multiple video encodings are
available, the Pexels adapter selects the largest MP4 variant. Images are stored under
`Library/Images`; videos are stored under `Library/Videos`. Filenames are sanitized and
include provider, media kind, provider ID, a readable label, and a short hash suffix.
Catalog paths always use root-relative forward-slash form such as
`Library/Images/pexels-photo-2014422-...jpg`.

Downloads stream through `Temp` while SHA-256 and byte count are calculated. Video files
are inspected with ffprobe when possible; provider metadata remains the fallback if a
probe cannot provide dimensions or duration.

## Download history

Every explicit acquisition is recorded persistently in `media_downloads`. The history is
append-only from the application's perspective and complements the canonical provider,
source, license, and attribution records. Each event retains the provider and raw provider
asset ID, media type, source and direct download URLs when applicable, attempt/completion
times, outcome status, resulting asset/path/hash, transferred byte count, HTTP status,
content type, sanitized provider metadata, and concise failure details.

History statuses have these meanings:

- `success`: a network transfer created a new catalog asset.
- `failed`: a transfer or post-transfer ingestion step failed; the asset relationship may
  be null.
- `duplicate`: a network transfer completed but its SHA-256 matched an existing asset.
- `reused`: the provider asset was already cataloged, so no network transfer occurred.
- `started`: the durable pre-transfer state; it may remain after an abrupt process or
  machine termination and makes interrupted attempts visible.

Provider metadata is recursively filtered to remove authorization, API-key, token,
password, and secret fields. API request headers and `PEXELS_API_KEY` are never written to
the database. A direct media URL is retained because it is part of the required transfer
audit, but provider API authorization headers are not.

## Duplicate behavior

- Repeating a search has no catalog side effects.
- Re-downloading the same provider asset returns the existing catalog record without
  another media download and appends a `reused` history event.
- Provider IDs are stored as `photo:<id>` or `video:<id>` so providers with separate ID
  namespaces cannot collide.
- If a different provider result downloads to an existing SHA-256, no second asset or
  file is created. The new source record is attached to the existing asset and the actual
  transfer is recorded as `duplicate`.
- `media_assets.sha256` remains the final database-level uniqueness guard.

The current schema stores one license record per physical asset. When identical bytes
arrive through multiple sources, the first asset license is retained and every source is
recorded. This preserves the existing schema; source-specific licenses can be introduced
later through a deliberate migration if a provider requires them.

## Pexels licensing and attribution

Downloaded Pexels assets record the Pexels License name and URL, creator details, source
page, and a suggested credit such as `Photo by <creator> on Pexels`. The current
[Pexels License](https://www.pexels.com/legal-pages/license/) says attribution is not
required but is appreciated, so `attribution_required` is stored as false while the
suggested credit is retained for production use. Always review the linked current license
and asset context before publication; people, brands, property, or other rights may need
separate consideration.

Run the tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Database changes

Schema changes belong in a new file under `migrations/versions`; do not edit a migration
that has already been used. Application startup commands call Alembic automatically and
verify that the database revision matches the current migration head.

The initial schema includes media assets, providers and source records, tags, licensing
and attribution, projects/episodes, stories, and asset usage history. SQLite triggers
maintain each asset's placement count and last-used timestamp from the usage-history rows.
Phase 2A initially reused that schema. Migration `0002_download_history` adds the
independent, historical `media_downloads` audit table without altering the original
provenance or usage tables. Phase 2B migration `0003_local_locations` adds the narrowly
scoped `media_locations` table for multiple local paths, origin, availability, efficient
unchanged-file checks, and missing/restored timestamps. Prior migrations remain unchanged.
