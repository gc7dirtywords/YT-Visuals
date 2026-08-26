# YT Visuals

Local system for cataloging and sourcing reusable images and video clips used in
YouTube production. It includes the SQLite catalog, a recursive local-library scanner,
basic catalog search, and a provider-neutral acquisition layer with Pexels as the first
provider.

The project does not yet support Pixabay, use AI services, automate DaVinci Resolve, or
assemble video.

## Producer-led Visual Plan workflow

The primary production path is a local, producer-controlled workspace. A ChatGPT Project
creates a strict Visual Plan v1 containing beat context and recommended manual searches;
YT-Visuals validates and stores that plan without making AI calls or interpreting the
narration. The producer explicitly chooses every asset.

Start the local server-rendered interface:

```powershell
.\.venv\Scripts\yt-visuals.exe web
```

The command binds to `127.0.0.1` first, prints the ready URL, and then opens one browser
tab. Use `--no-browser` to suppress automatic opening. An explicit `--host 0.0.0.0`
allows LAN access and prints a security warning plus the likely LAN URL; the default
remains loopback-only. If the browser cannot be launched, the server keeps running and
prints the URL to open manually.

Configure Pexels from **Settings → Integrations → Pexels**. A saved key is held by the
operating-system keyring (Windows Credential Manager) under service `YT-Visuals` and
username `PEXELS_API_KEY`; it is never returned to the browser. The environment variable
`PEXELS_API_KEY` takes precedence over the saved key. Test Connection performs one
minimal authenticated provider request, and Remove Stored Key removes only the keyring
entry—it does not change an environment override.

The home page imports a Visual Plan JSON file. Each story workspace shows one card per
beat with narration, requested visual, guidance, copyable search phrases, up to three
deterministic local-catalog candidates, current selection and provenance/license details.
Nothing is auto-selected. A catalog result can be selected, hidden for only that beat,
restored, or replaced later.

Manual import supports HTTPS Pexels photo and video page URLs. The page identity is
resolved through the Pexels API and the existing hardened acquisition pipeline; arbitrary
web-page scraping and arbitrary direct-media downloads are intentionally unsupported.
Local image/video uploads are validated with the existing media inspectors, SHA-256
deduplicated, cataloged as local imports, and assigned no invented license.

The workspace builds a DaVinci-ready folder at `Projects/<story_id>/Edit/`. Its `Visuals`
folder contains only current selections in stable beat order, using same-filesystem hard
links where possible and safe copies otherwise. `manifest.csv` records beat, asset,
source, creator, and license context. Rebuilding never mutates Library masters. The
producer storyboard is written to `Edit/storyboard.pdf` and clearly includes both
selected and unselected beats without requiring an alignment score or automated review.

The contract, JSON Schema, and example are:

- `docs/17-visual-plan-v1.md`
- `schemas/visual-plan.v1.schema.json`
- `examples/visual-plan.v1.json`

The Phase 4/5 Visual Request and review CLI remains available as a separate legacy path.

## Phase 4: manual visual-review workflow

YT-Visuals is not an AI application. Story interpretation, beat selection, editorial
judgment, and visual alignment scoring belong to a normal ChatGPT Project outside this
repository. YT-Visuals only validates structured handoff files, searches the local
catalog deterministically, creates review artifacts, and applies explicit structured
review decisions. It makes no OpenAI or LLM calls and performs no semantic interpretation.

The Phase 4 handoff is entirely manual and file based:

1. ChatGPT creates a strict `visual_request` JSON document from a finished story.
2. YT-Visuals starts a workflow and searches existing local catalog media first.
3. YT-Visuals writes a machine-readable Candidate Report, a visual storyboard PDF, and
   an editable Review Template under `Projects/VisualWorkflows/<workflow-id>/`.
4. The user uploads the storyboard and request context to ChatGPT for visual review.
5. ChatGPT returns a completed `visual_review` JSON document.
6. YT-Visuals imports the review, locks accepted beats, and locally re-sources only
   rejected or search-blocked beats. The cycle repeats until all beats are locked.

An accepted candidate requires an integer alignment score of at least 90. A score below
90 must request replacement; a score of 90 or more may still request replacement. The
application validates these rules but never calculates the score. Accepted locks persist
across request revisions only when the stable beat ID and canonical compatibility
fingerprint remain unchanged.

`blocked_no_candidate` means deterministic local search found no eligible candidate. Its
Review Template entry asks for explicit revised search directives and may return to
sourcing. `blocked_missing` means an already locked asset disappeared or changed bytes;
the lock is retained, the beat has no editable review entry, and normal sourcing cannot
replace it.

Structured licenses permitting commercial use and modification are eligible. Missing or
insufficient structured license data remains eligible for visual review but is visibly
marked `LICENSE: UNKNOWN`; a structured prohibition excludes the asset. Publication-time
license clearance is not implemented. Automatic Pexels/Pixabay fallback is also deferred;
Phase 4 workflow sourcing is local only even though the existing explicit provider CLI
remains available.

The immutable v1 contract schemas are stored in `schemas/`. Validate and run the manual
workflow from PowerShell:

```powershell
.\.venv\Scripts\yt-visuals.exe visual request validate .\request.json --json
.\.venv\Scripts\yt-visuals.exe visual workflow start .\request.json
.\.venv\Scripts\yt-visuals.exe visual workflow source <workflow-id>
.\.venv\Scripts\yt-visuals.exe visual workflow status <workflow-id>
.\.venv\Scripts\yt-visuals.exe visual workflow artifacts <workflow-id>
.\.venv\Scripts\yt-visuals.exe visual workflow review <workflow-id> .\completed-review.json
```

Import an intentional request revision with the explicit workflow ID; matching
`story_id` alone never selects a workflow:

```powershell
.\.venv\Scripts\yt-visuals.exe visual workflow revise <workflow-id> .\request-v2.json
```

Only explicit `search_directives`, filters, media preference, technical constraints,
prior-usage policy, repeat policy, and recorded correction directives affect retrieval.
Narration, requested-visual prose, concepts, and editorial criteria are retained for
human review but are never converted into search behavior.

## Media service layer

`yt_visuals.services.MediaCatalogService` is the application boundary for catalog reads
and usage writes. It returns validated Pydantic models instead of SQLAlchemy objects or
CLI-formatted text. This keeps search, ranking, asset detail, status, recent-usage, and
usage-recording rules reusable by a future MCP server without copying business logic.

The CLI remains a presentation adapter: existing `library search` and `library status`
commands call the service and preserve their established human and JSON output. Phase 3
does not include an MCP server, HTTP server, AI integration, or script ingestion.

Example Python usage:

```python
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.services import MediaCatalogService, SearchMediaRequest

settings = Settings.load()
engine = initialize_database(settings)
service = MediaCatalogService(engine)

result = service.search_media(
    SearchMediaRequest(
        query="abandoned factory",
        media_type="image",
        orientation="landscape",
        usage="unused",
        limit=10,
    )
)
print(result.model_dump_json(indent=2))
engine.dispose()
```

Service requests and results reject unknown fields and publish JSON Schema through
Pydantic's `model_json_schema()`. A ranked search response has a stable shape similar to:

```json
{
  "query": "abandoned factory",
  "returned": 1,
  "candidates": [
    {
      "rank": 1,
      "score": 137,
      "score_reasons": ["available:+40", "exact_tag:factory:+30"],
      "asset_id": 12,
      "relative_path": "Library/Images/factory.jpg",
      "current_location": "Library/Images/factory.jpg",
      "media_type": "image",
      "orientation": "landscape",
      "available": true,
      "providers": ["pexels"],
      "tags": ["factory", "industrial"],
      "usage_count": 0,
      "recent_usage_count": 0
    }
  ]
}
```

Asset-detail results include every known location, provider/source and creator data,
license/attribution, tags, technical identity, availability, and recent usage. Status
results distinguish local-import and provider-download locations. Since scan executions
are not yet stored as their own records, `last_scan_at` and `last_scan_status` are null.

Usage writes require a caller-generated `idempotency_key`. Repeating the same request with
the same key returns the original row; reusing the key for different content is rejected.
Usage can be associated with a project, a story (with its project derived and validated),
or left unassigned for later organization. Missing assets are rejected unless the caller
explicitly sets `allow_missing=True`.

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
unchanged-file checks, and missing/restored timestamps. Phase 3 migration
`0004_usage_context` makes story context optional and adds project context, a visual usage
reference, and a unique idempotency key to usage history. The existing usage-count
triggers remain the single source of truth. Prior migrations remain unchanged.
