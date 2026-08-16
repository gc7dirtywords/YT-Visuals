# YT Visuals

Local foundation for cataloging reusable images and video clips used in YouTube
production. The current scope is intentionally limited to configuration, a SQLite
catalog, versioned migrations, data models, health checks, and tests.

The project does not yet scan or download media, call stock-media APIs, generate
manifests, use AI services, or assemble video.

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

No `.env` file is required. `YT_VISUALS_ROOT` may be set as an environment variable
if commands need to operate on a different compatible root.

## Commands

Create the database and apply all pending migrations:

```powershell
.\.venv\Scripts\yt-visuals.exe db upgrade
```

Run the complete environment check. This also initializes or migrates the database:

```powershell
.\.venv\Scripts\yt-visuals.exe doctor
```

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

