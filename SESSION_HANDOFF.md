# Session Handoff

## Release storage recovery

- Alembic revision `0017` retains the nullable `video_releases.storage_path` column.
- Existing rows with `storage_path IS NULL` continue to resolve through their UUID directory.
- New releases receive a stable, Windows/SMB-safe, human-readable storage component.
- Changing a release's display title does not change its storage component.
- Stories, artifacts, transcripts, uploads, downloads, and file browsing use one release-path resolver.
- The duplicate, sessionless `get_release()` regression has been removed.

## Container behavior

Container startup runs the normal Alembic upgrade only. It never moves, renames, deletes,
or creates release directories. The former `Tools/migrate_release_paths.sh` script is no
longer included in the image.

The next image is safe to start against production revision `0017`, where all current
`storage_path` values are null and the real release directories still use UUID names.
Existing `.backup-*` symbolic links are not modified.

## Controlled one-time migration

Generate a read-only report inside the container:

```sh
yt-visuals release-storage migrate --dry-run --json \
  --report /config/release-storage-plan.json
```

The report includes database IDs and names, source/destination types, file counts,
missing and empty directories, conflicts, and `.backup-*` symlinks labeled as aliases.
Actual execution is a separate, explicitly confirmed operation. Do not run it on Draven
until the dry-run report has been reviewed and production conversion is authorized.

## CI/CD

`.github/workflows/publish-ghcr.yml` builds and publishes both `latest` and commit-SHA
tags to `ghcr.io/gc7dirtywords/yt-visuals` after a push to `main`.
