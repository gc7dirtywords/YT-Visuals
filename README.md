# YT Visuals

Local system for cataloging and sourcing reusable images and video clips used in
YouTube production. It currently includes the SQLite catalog foundation plus a
provider-neutral search and acquisition layer with Pexels as the first provider.

The project does not yet scan existing media, support Pixabay, generate manifests,
use AI services, or assemble video.

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
provenance or usage tables.
