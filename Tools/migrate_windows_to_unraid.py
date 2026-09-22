"""Prepare a copy-first migration of a YT-ChannelOps Windows installation.

This utility never writes to the source installation.  It creates a SQLite
backup, verifies it, makes a staged copy of the durable roots, and only then
updates explicit, allowlisted absolute path columns in the copied database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOTS = {
    "library": ("Library", "/library"),
    "projects": ("Projects", "/projects"),
    "releases": ("Releases", "/releases"),
    "temp": ("Temp", "/temp"),
}
PATH_COLUMNS = {
    "media_assets": ("relative_path",),
    "media_locations": ("relative_path",),
    "media_downloads": ("relative_path",),
    "projects": ("project_path",),
    "candidate_packages": (
        "candidate_report_path",
        "storyboard_path",
        "review_template_path",
    ),
}
COPIED_ROOTS = ("projects", "library", "releases")


@dataclass(frozen=True)
class TreeSummary:
    name: str
    exists: bool
    files: int
    bytes: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_checks(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        integrity = [row[0] for row in connection.execute("PRAGMA integrity_check")]
        foreign_keys = [list(row) for row in connection.execute("PRAGMA foreign_key_check")]
    finally:
        connection.close()
    return {"integrity_check": integrity, "foreign_key_check": foreign_keys}


def assert_database_healthy(path: Path) -> dict[str, Any]:
    checks = sqlite_checks(path)
    if checks["integrity_check"] != ["ok"] or checks["foreign_key_check"]:
        raise RuntimeError(f"SQLite validation failed for {path}: {checks}")
    return checks


def backup_sqlite(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()


def summarize_tree(name: str, path: Path) -> TreeSummary:
    if not path.exists():
        return TreeSummary(name, False, 0, 0)
    files = [item for item in path.rglob("*") if item.is_file()]
    return TreeSummary(name, True, len(files), sum(item.stat().st_size for item in files))


def tree_fingerprint(path: Path) -> dict[str, Any]:
    """Hash file content and relative names so a copied durable root is provable."""
    digest = hashlib.sha256()
    files = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: item.relative_to(path).as_posix())
    total_bytes = 0
    for item in files:
        relative = item.relative_to(path).as_posix()
        file_digest = sha256_file(item)
        size = item.stat().st_size
        digest.update(f"{relative}\0{size}\0{file_digest}\n".encode("utf-8"))
        total_bytes += size
    return {"files": len(files), "bytes": total_bytes, "sha256": digest.hexdigest()}


def windows_path_remap(value: str, source_root: Path) -> str | None:
    """Return a Linux root remap only for an exact known application root."""
    normalized = value.replace("/", "\\").rstrip("\\")
    for _name, (windows_child, target_root) in ROOTS.items():
        source_prefix = str(source_root / windows_child).replace("/", "\\").rstrip("\\")
        if normalized.casefold() == source_prefix.casefold():
            return target_root
        if normalized.casefold().startswith(source_prefix.casefold() + "\\"):
            suffix = normalized[len(source_prefix):].lstrip("\\").replace("\\", "/")
            return f"{target_root}/{suffix}"
    return None


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')}


def remap_database_paths(database: Path, source_root: Path) -> list[dict[str, str]]:
    """Mutate only the copied database and only allowlisted path cells."""
    remaps: list[dict[str, str]] = []
    connection = sqlite3.connect(database)
    try:
        for table, columns in PATH_COLUMNS.items():
            available = table_columns(connection, table)
            if not available:
                continue
            for column in columns:
                if column not in available:
                    continue
                primary_key = "id" if "id" in available else "rowid"
                rows = connection.execute(
                    f'SELECT {primary_key}, "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
                ).fetchall()
                for row_id, value in rows:
                    if not isinstance(value, str):
                        continue
                    replacement = windows_path_remap(value, source_root)
                    if replacement is None or replacement == value:
                        continue
                    connection.execute(
                        f'UPDATE "{table}" SET "{column}" = ? WHERE {primary_key} = ?',
                        (replacement, row_id),
                    )
                    remaps.append(
                        {"table": table, "column": column, "id": str(row_id), "from": value, "to": replacement}
                    )
        connection.commit()
    finally:
        connection.close()
    return remaps


def path_inventory(database: Path, source_root: Path) -> list[dict[str, Any]]:
    """Inspect only the explicit persisted filesystem fields allowed for remap."""
    result: list[dict[str, Any]] = []
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        for table, columns in PATH_COLUMNS.items():
            available = table_columns(connection, table)
            for column in columns:
                if column not in available:
                    continue
                values = [row[0] for row in connection.execute(f'SELECT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL')]
                remappable = sum(1 for value in values if isinstance(value, str) and windows_path_remap(value, source_root) is not None)
                windows_absolute = sum(1 for value in values if isinstance(value, str) and len(value) >= 3 and value[1:3] in {":\\", ":/"})
                result.append({"table": table, "column": column, "non_null": len(values), "known_root_remappable": remappable, "other_windows_absolute": windows_absolute - remappable})
    finally:
        connection.close()
    return result


def _canonical_cell(value: Any, source_root: Path) -> Any:
    if not isinstance(value, str):
        return value
    remapped = windows_path_remap(value, source_root)
    if remapped is not None:
        return remapped
    return value


def database_summary(database: Path, source_root: Path) -> dict[str, dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        result: dict[str, dict[str, Any]] = {}
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            rows = connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            digest = hashlib.sha256()
            for row in rows:
                digest.update(json.dumps([_canonical_cell(value, source_root) for value in row], default=str, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
                digest.update(b"\n")
            result[table] = {"rows": len(rows), "columns": columns, "content_sha256": digest.hexdigest()}
        return result
    finally:
        connection.close()


def verify_staged_copy(source_root: Path, staging_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    staging_root = staging_root.resolve()
    source_db = source_root / "Data" / "catalog.sqlite3"
    target_db = staging_root / "config" / "catalog.sqlite3"
    if not source_db.is_file() or not target_db.is_file():
        raise RuntimeError("both source and staged catalog.sqlite3 files are required")
    result: dict[str, Any] = {
        "source_checks": assert_database_healthy(source_db),
        "target_checks": assert_database_healthy(target_db),
        "source_summary": database_summary(source_db, source_root),
        "target_summary": database_summary(target_db, source_root),
        "durable_tree_verification": {},
    }
    if result["source_summary"] != result["target_summary"]:
        raise RuntimeError("staged database row counts or canonical content do not match source")
    for name in COPIED_ROOTS:
        source_directory = source_root / ROOTS[name][0]
        target_directory = staging_root / name
        if not source_directory.exists():
            if target_directory.exists():
                raise RuntimeError(f"unexpected staged {name} root")
            result["durable_tree_verification"][name] = {"source_exists": False, "target_exists": False}
            continue
        if not target_directory.is_dir():
            raise RuntimeError(f"staged {name} root is missing")
        source_tree = tree_fingerprint(source_directory)
        target_tree = tree_fingerprint(target_directory)
        if source_tree != target_tree:
            raise RuntimeError(f"staged {name} content does not match source")
        result["durable_tree_verification"][name] = source_tree
    result["verified"] = True
    return result


def migrate(source_root: Path, staging_root: Path, *, dry_run: bool) -> dict[str, Any]:
    source_root = source_root.resolve()
    staging_root = staging_root.resolve()
    source_db = source_root / "Data" / "catalog.sqlite3"
    if not source_db.is_file():
        raise RuntimeError(f"source database does not exist: {source_db}")
    if source_root == staging_root or source_root in staging_root.parents:
        raise RuntimeError("staging root must be outside the source installation")
    source_checks = assert_database_healthy(source_db)
    trees = {name: summarize_tree(name, source_root / windows_child) for name, (windows_child, _target) in ROOTS.items()}
    plan = {
        "source_root": str(source_root),
        "staging_root": str(staging_root),
        "source_database": str(source_db),
        "source_database_sha256": sha256_file(source_db),
        "source_checks": source_checks,
        "path_inventory": path_inventory(source_db, source_root),
        "durable_trees": {name: summary.__dict__ for name, summary in trees.items()},
        "copy_roots": [name for name in COPIED_ROOTS if trees[name].exists],
        "temp_copied": False,
        "dry_run": dry_run,
    }
    if dry_run:
        return plan
    if staging_root.exists() and any(staging_root.iterdir()):
        raise RuntimeError("staging root must be new or empty")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    config_root = staging_root / "config"
    backup = config_root / "backups" / f"catalog-pre-unraid-{timestamp}.sqlite3"
    backup_sqlite(source_db, backup)
    backup_sha = sha256_file(backup)
    source_sha_after_backup = sha256_file(source_db)
    if source_sha_after_backup != plan["source_database_sha256"]:
        raise RuntimeError("source database changed while backup was being created; stop the Windows application and retry")
    plan["backup_database"] = str(backup)
    plan["backup_sha256"] = backup_sha
    plan["source_database_sha256_after_backup"] = source_sha_after_backup
    plan["backup_checks"] = assert_database_healthy(backup)
    target_db = config_root / "catalog.sqlite3"
    shutil.copy2(backup, target_db)
    for name in COPIED_ROOTS:
        source_directory = source_root / ROOTS[name][0]
        if source_directory.exists():
            shutil.copytree(source_directory, staging_root / name, dirs_exist_ok=False)
    remaps = remap_database_paths(target_db, source_root)
    plan["path_remaps"] = remaps
    plan["target_database"] = str(target_db)
    plan.update(verify_staged_copy(source_root, staging_root))
    (config_root / "migration-report.json").write_text(json.dumps(plan, indent=2, sort_keys=True), encoding="utf-8")
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--staging-root", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="create the verified staged migration copy")
    mode.add_argument("--verify-staging", action="store_true", help="verify an existing staged migration copy")
    args = parser.parse_args()
    try:
        result = verify_staged_copy(args.source_root, args.staging_root) if args.verify_staging else migrate(args.source_root, args.staging_root, dry_run=not args.execute)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
