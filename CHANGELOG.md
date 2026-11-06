# Changelog

All notable changes to YT-Visuals will be documented in this file.

## [Unreleased]

### Added
- `storage_path` column to `video_releases` table (Alembic migration 0017)
- Human-readable folder names for release assets instead of UUID paths

### Changed
- Release artifact folders now use `storage_path` (defaults to name) instead of raw `id` (UUID)
- New releases are created with their name as the folder path component immediately

### Migration Notice
**Automated migration included**: The repository includes a shell script at `Tools/migrate_release_paths.sh` that:
- Runs automatically on Unraid container startup when pulling new images
- Converts existing UUID-based release folders to name-based paths
- Creates symlinks as backup before renaming (safe, idempotent)

### Files Added
- `migrations/versions/0017_add_storage_path_column.py` - Database migration
- `Tools/migrate_release_paths.sh` - Unraid startup migration script

### Backward Compatibility
- Existing deployments continue to work until migration runs
- New releases use name-based paths from creation
- Symlink backup ensures zero data loss during migration

---

## [0.9B] - Initial Phase 9 Release

Initial release of YT-Visuals with visual workflow planning, review, and production management.
