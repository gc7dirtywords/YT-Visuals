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
**Automated migration included**: The Docker image includes `/Tools/migrate_release_paths.sh` that:
- Runs automatically on container startup (via docker-entrypoint.sh) after Alembic upgrade
- Converts existing UUID-based release folders to name-based paths
- Creates symlinks as backup before renaming (safe, idempotent)

**Startup order on Unraid Docker**:
1. Container starts with new image
2. `docker-entrypoint.sh` runs first: creates volume directories → links to app roots
3. Alembic runs `upgrade head` (applies migration 0017 adding storage_path column)
4. Migration script `/app/Tools/migrate_release_paths.sh` runs and renames folders
5. Application starts with gunicorn

**Files in Docker image**:
- `/app/Tools/migrate_release_paths.sh` - Migration script (read-only, part of image)
- `/app/Tools/migration.log` - Created by migration script (writable volume mount recommended)

**Unraid setup**: Mount `/config` volume to include `.migration_complete` marker if desired.

### Files Added
- `migrations/versions/0017_add_storage_path_column.py` - Database migration
- `Tools/migrate_release_paths.sh` - Unraid startup migration script

### Backward Compatibility
- Existing deployments continue to work until migration runs
- New releases use name-based paths from creation
- Symlink backup ensures zero data loss during migration

### Bug Fixes
- Migration script now sanitizes release names (replaces spaces with underscores, removes special characters) to prevent filesystem errors on Unix systems

---

## [0.9B] - Initial Phase 9 Release

Initial release of YT-Visuals with visual workflow planning, review, and production management.
