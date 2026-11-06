# Changelog

All notable changes to YT-Visuals will be documented in this file.

## [Unreleased]

### Added
- `storage_path` column to `video_releases` table (Alembic migration 0017)
- Stable, Windows/SMB-safe human-readable storage paths for new releases
- Explicit `yt-visuals release-storage migrate` audit and one-time migration utility
- Content manifests, durable migration journaling, conflict detection, and interrupted-move recovery

### Changed
- Release storage resolution is centralized for stories, artifacts, transcripts, and file browsing
- Existing releases with `storage_path IS NULL` continue to use their UUID directories
- Display-title changes no longer change a release's stable storage path
- Release-directory migration is never run during container startup

### Migration Notice
The next deployment does not rename any release directories. Run
`yt-visuals release-storage migrate --dry-run --json` separately to inventory legacy
UUID directories. Filesystem moves require `--execute`, an exact confirmation token,
and should be performed only after review and backup.

### Backward Compatibility
- Existing UUID directories remain authoritative while `storage_path` is null
- Existing `.backup-*` symlinks are reported as aliases and are not treated as backups
- Missing and empty legacy directories are reported without being created or deleted

### Bug Fixes
- Restored the original session-scoped release lookup API that had been overwritten
- Removed the defective startup shell migration and misleading symlink-backup behavior
- Corrected transcript readiness and all release file consumers to use the same path resolver

---

## [0.9B] - Initial Phase 9 Release

Initial release of YT-Visuals with visual workflow planning, review, and production management.
