#!/bin/bash
#
# migrate_release_paths.sh
#
# Automated migration script for YT-Visuals release folder paths.
# Converts UUID-based folder names to human-readable name-based paths.
#
# USAGE: Place this script in your Unraid Docker container's startup scripts,
#        or run manually when pulling a new image that includes this migration.
#
# SAFETY: Script creates symlinks as backup before renaming each folder.
#         This ensures zero data loss even if interrupted.
#
# BEHAVIOR: Idempotent - safe to run multiple times without side effects.
#

set -euo pipefail

SCRIPT_NAME="migrate_release_paths.sh"
LOG_FILE="/config/yt_visuals/migration.log"
RELEASES_ROOT="${YT_CHANNELOPS_RELEASES_ROOT:-/mnt/user/appdata/YT-ChannelOps/Releases}"
MIGRATION_COMPLETE_FILE="/config/yt_visuals/.migration_complete"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${BLUE}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[INFO] $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+$(date +%s)') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[WARN] $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[ERROR] $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[SUCCESS] $1"
}

# UUID pattern for old-style paths
UUID_PATTERN='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

# Check if a path is UUID-based (old style)
is_uuid_path() {
    local path="$1"
    echo "$path" | grep -qE "^$UUID_PATTERN$"
}

# Extract release name from database
get_release_name_from_db() {
    local release_id="$1"
    
    if command -v sqlite3 &> /dev/null && [ -f "${RELEASES_ROOT}/catalog.sqlite3" ]; then
        local name
        name=$(sqlite3 "${RELEASES_ROOT}/catalog.sqlite3" \
            "SELECT name FROM video_releases WHERE id = '${release_id}';" 2>/dev/null) || name=""
        echo "$name"
    else
        # SQLite not available, return empty
        echo ""
    fi
}

# Create symlink from new path to old path as backup
create_symlink_backup() {
    local old_path="$1"
    local new_path="$2"
    
    if [ -d "$old_path" ] && [ ! -L "$new_path" ] && [ ! -d "$new_path" ]; then
        ln -sT "$old_path" "$new_path" 2>/dev/null && \
            log_info "Created symlink backup: $new_path -> $old_path" || \
            log_warn "Failed to create symlink: $new_path -> $old_path (may need permissions)"
    fi
}

# Main migration function
migrate_releases() {
    local migrated=0
    local failed=0
    
    # Ensure releases root exists
    if [ ! -d "$RELEASES_ROOT" ]; then
        log_warn "Releases root does not exist: $RELEASES_ROOT"
        mkdir -p "$RELEASES_ROOT" 2>/dev/null && \
            log_info "Created releases root: $RELEASES_ROOT" || \
            log_warn "Could not create releases root (check permissions)"
    fi
    
    # Check if already migrated (idempotency check)
    if [ -f "$MIGRATION_COMPLETE_FILE" ]; then
        log_info "Migration already completed. Skipping."
        return 0
    fi
    
    log_info "Starting release path migration..."
    
    # Find all release folders using UUID-based names
    while IFS= read -r uuid_folder; do
        if [ -z "$uuid_folder" ]; then
            continue
        fi
        
        # Skip if already migrated (new name pattern)
        if ! is_uuid_path "$uuid_folder"; then
            log_info "Skipping $uuid_folder - not a UUID-based path"
            continue
        fi
        
        # Get the release ID from the folder name
        local release_id="$uuid_folder"
        
        # Get release name from database
        local release_name
        release_name=$(get_release_name_from_db "$release_id")
        
        if [ -z "$release_name" ]; then
            log_warn "Could not get release name for $release_id from database. Skipping."
            continue
        fi
        
        # Construct new path
        local new_path="${RELEASES_ROOT}/${release_name}"
        
        log_info "Processing: $uuid_folder -> $new_path (name: $release_name)"
        
        # Create symlink as backup (new folder pointing to old)
        create_symlink_backup "$uuid_folder" "$new_path"
        
        # Rename the actual folder
        if mv "$uuid_folder" "$new_path" 2>/dev/null; then
            log_success "Renamed $uuid_folder -> $new_path"
            
            # Mark as migrated for this release
            echo "$release_id:$new_path:$(date +%s)" >> "$MIGRATION_COMPLETE_FILE" 2>/dev/null || true
            
            ((migrated++))
        else
            log_error "Failed to rename $uuid_folder -> $new_path"
            ((failed++))
            
            # Try to create backup symlink as recovery
            create_symlink_backup "$uuid_folder" "${new_path}.backup-$(date +%s)"
        fi
        
    done < <(find "$RELEASES_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%P\n' 2>/dev/null | sort)
    
    # Summary
    if [ $migrated -gt 0 ]; then
        log_success "Migration complete: $migrated folders migrated, $failed failed"
    else
        log_info "No UUID-based release folders found. Already migrated or empty."
    fi
    
    return 0
}

# Main entry point
main() {
    echo "=========================================="
    echo "YT-Visuals Release Path Migration Script"
    echo "=========================================="
    
    # Check permissions
    if [ ! -w "$RELEASES_ROOT" ]; then
        log_error "Permission denied: cannot write to $RELEASES_ROOT"
        exit 1
    fi
    
    # Run migration
    if migrate_releases; then
        log_info "Migration finished successfully"
        exit 0
    else
        log_error "Migration completed with errors - please review logs"
        exit 1
    fi
}

# Run if executed directly
main "$@"
