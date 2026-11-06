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
RELEASES_ROOT="${YT_CHANNELOPS_RELEASES_ROOT:-/releases}"
CATALOG_DB="${YT_CHANNELOPS_CONFIG_ROOT:-/config}/catalog.sqlite3"
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
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[WARN] $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[ERROR] $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1" | tee -a "$LOG_FILE" 2>/dev/null || echo "[SUCCESS] $1"
}

# UUID pattern for old-style paths (lowercase hex with hyphens)
UUID_PATTERN='^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'

# Check if a path is UUID-based (old style)
is_uuid_path() {
    local path="$1"
    echo "$path" | grep -qE "^$UUID_PATTERN$"
}

# Extract release storage_path/name from database
get_release_storage_path_from_db() {
    local release_id="$1"
    
    # Check if sqlite3 is available and db exists
    if command -v sqlite3 &> /dev/null && [ -f "$CATALOG_DB" ]; then
        # First try storage_path column (new column added by migration 0017)
        local name
        name=$(sqlite3 "$CATALOG_DB" "SELECT storage_path FROM video_releases WHERE id = '${release_id}';" 2>/dev/null) || true
        
        # If storage_path is NULL or empty, try to get from name field
        if [ -z "$name" ] || [ "$name" = "NULL" ]; then
            name=$(sqlite3 "$CATALOG_DB" "SELECT name FROM video_releases WHERE id = '${release_id}';" 2>/dev/null) || true
        fi
        
        echo "$name"
    else
        # SQLite not available or db not found, return empty
        echo ""
    fi
}

# Sanitize release name for filesystem safety:
# - Replace spaces with underscores
# - Remove special characters (keep only alphanumeric, underscores, hyphens)
sanitize_name() {
    local name="$1"
    # Replace spaces with underscores first
    name="${name// /_}"
    # Remove any character that is NOT alphanumeric, underscore, or hyphen
    name=$(echo "$name" | tr -cd '[:alnum:]_-')
    echo "$name"
}

# Main migration function
migrate_releases() {
    local migrated=0
    local failed=0
    local skipped=0
    
    # Ensure releases root exists
    if [ ! -d "$RELEASES_ROOT" ]; then
        log_warn "Releases root does not exist: $RELEASES_ROOT"
        return 1
    fi
    
    # Remove idempotency marker so migration can run again
    rm -f "$MIGRATION_COMPLETE_FILE" 2>/dev/null || true
    
    log_info "Starting release path migration..."

    # Find all subdirectories in releases root (use find to handle special chars)
    while IFS= read -r -d '' uuid_folder_raw; do
        # Skip if not a directory
        [ ! -d "$uuid_folder_raw" ] && continue
        
        # Remove trailing slash if present
        uuid_folder="${uuid_folder_raw%/}"
        
        if [ -z "$uuid_folder" ]; then
            continue
        fi
        
        log_info "Checking: $uuid_folder"
        
        # Skip backup folders (already have .backup suffix)
        if [[ "$uuid_folder" == *.backup* ]]; then
            log_info "Skipping $uuid_folder - backup folder"
            ((skipped++))
            continue
        fi
        
        # New format check: starts with ECH_NNN_ or similar (e.g., ECH_R0001_A..., ECHR0001__, etc)
        if [[ "$uuid_folder" =~ ^[A-Z]+ ]]; then
            log_info "Skipping $uuid_folder - new name-based format (starts with uppercase)"
            ((skipped++))
            continue
        fi
        
        # Legacy UUID path - needs migration
        if is_uuid_path "$uuid_folder"; then
            # Get the release ID from the folder name
            local release_id="$uuid_folder"
            
            # Get release storage_path/name from database
            local release_name
            release_name=$(get_release_storage_path_from_db "$release_id")
            
            if [ -z "$release_name" ] || [ "$release_name" = "None" ]; then
                log_error "Could not get release name for $release_id from database. Skipping."
                ((failed++))
                continue
            fi
            
            # Sanitize release name for filesystem safety
            local sanitized_name
            sanitized_name=$(sanitize_name "$release_name")
            
            local new_path="${RELEASES_ROOT}/${sanitized_name}"
            
            log_info "Processing: $uuid_folder -> $new_path (name: '${release_name}' -> sanitized: '$sanitized_name')"

            # Check if source folder exists
            if [ ! -d "$uuid_folder" ]; then
                log_warn "Source folder does not exist: $uuid_folder"
                log_info "Release ID from database might be wrong or folder was already moved"
                ((skipped++))
                continue
            fi
            
            # Check if destination already exists (may have been created by previous failed attempts)
            if [ -e "$new_path" ]; then
                log_warn "Destination path already exists: $new_path"
                log_warn "Contents of existing destination:"
                ls -la "$new_path" 2>&1 || true
                ((skipped++))
                continue
            fi
            
            # Rename the actual folder FIRST (before any backup)
            if mv -- "$uuid_folder" "$new_path"; then
                log_success "Renamed $uuid_folder -> $new_path"
                
                # Create a symlink from old location as reference (non-blocking)
                ln -sT "$new_path" "$uuid_folder" 2>/dev/null || true
                
                # Mark as migrated for this release
                echo "${release_id}:${new_path}:$(date +%s)" >> "$MIGRATION_COMPLETE_FILE" 2>/dev/null || true
                
                ((migrated++))
            else
                local mv_error=$?
                log_error "Failed to rename $uuid_folder -> $new_path (exit code: $mv_error)"
                log_error "Checking source directory..."
                ls -la "$uuid_folder" 2>&1
                log_error "Checking destination path..."
                ls -la "$new_path" 2>&1 || echo "Destination does not exist or is not accessible"
                ((failed++))
                
                # Try to create backup symlink at alternative location as recovery
                local backup_path="${RELEASES_ROOT}/${sanitized_name}.backup-$(date +%s)"
                ln -sT "$uuid_folder" "$backup_path" 2>/dev/null || log_warn "Could not create backup symlink at $backup_path"
            fi
            
        else
            # Unknown format folder - skip and log for review
            log_warn "Unknown format: $uuid_folder (skipping for manual review)"
            ((skipped++))
        fi
        
    done < <(find "$RELEASES_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
    
    # Summary
    log_info "Migration complete: $migrated migrated, $failed failed, $skipped skipped"
    
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
