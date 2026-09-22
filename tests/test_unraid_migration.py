from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[1] / "Tools" / "migrate_windows_to_unraid.py"
_SPEC = importlib.util.spec_from_file_location("unraid_migration", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
migrate = _MODULE.migrate
path_inventory = _MODULE.path_inventory
verify_staged_copy = _MODULE.verify_staged_copy
windows_path_remap = _MODULE.windows_path_remap


def _source_installation(root: Path) -> None:
    (root / "Data").mkdir(parents=True)
    (root / "Library" / "Images").mkdir(parents=True)
    (root / "Projects" / "story-a" / "Documents").mkdir(parents=True)
    (root / "Releases" / "release-a").mkdir(parents=True)
    (root / "Library" / "Images" / "image.jpg").write_bytes(b"image")
    (root / "Projects" / "story-a" / "Documents" / "script.txt").write_text("script", encoding="utf-8")
    (root / "Releases" / "release-a" / "edit.zip").write_bytes(b"zip")
    connection = sqlite3.connect(root / "Data" / "catalog.sqlite3")
    connection.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE media_assets (id INTEGER PRIMARY KEY, relative_path TEXT);
        CREATE TABLE candidate_packages (id INTEGER PRIMARY KEY, storyboard_path TEXT, candidate_report_path TEXT, review_template_path TEXT);
        """
    )
    connection.execute("INSERT INTO media_assets VALUES (1, ?)", (str(root / "Library" / "Images" / "image.jpg"),))
    connection.execute("INSERT INTO candidate_packages VALUES (1, ?, NULL, NULL)", (str(root / "Projects" / "story-a" / "Edit" / "storyboard.pdf"),))
    connection.commit()
    connection.close()


def test_windows_path_remap_is_limited_to_known_roots(tmp_path: Path) -> None:
    source = tmp_path / "YT-Visuals"
    assert windows_path_remap(r"D:\YT-Visuals\Library\Images\a.jpg", source) is None
    assert windows_path_remap(r"C:\outside\file.txt", source) is None
    assert windows_path_remap(str(source / "Library" / "Images" / "a.jpg"), source) == "/library/Images/a.jpg"


def test_copy_first_migration_preserves_content_and_remaps_known_paths(tmp_path: Path) -> None:
    source = tmp_path / "source"
    staging = tmp_path / "staging"
    _source_installation(source)
    dry_run = migrate(source, staging, dry_run=True)
    assert dry_run["copy_roots"] == ["projects", "library", "releases"]
    assert sum(item["known_root_remappable"] for item in path_inventory(source / "Data" / "catalog.sqlite3", source)) == 2
    assert not staging.exists()
    result = migrate(source, staging, dry_run=False)
    assert result["verified"] is True
    assert len(result["backup_sha256"]) == 64
    assert result["source_database_sha256_after_backup"] == result["source_database_sha256"]
    assert len(result["path_remaps"]) == 2
    assert (staging / "library" / "Images" / "image.jpg").read_bytes() == b"image"
    assert (staging / "projects" / "story-a" / "Documents" / "script.txt").read_text(encoding="utf-8") == "script"
    assert (staging / "releases" / "release-a" / "edit.zip").read_bytes() == b"zip"
    assert verify_staged_copy(source, staging)["durable_tree_verification"]["library"]["files"] == 1
    source_connection = sqlite3.connect(source / "Data" / "catalog.sqlite3")
    target_connection = sqlite3.connect(staging / "config" / "catalog.sqlite3")
    try:
        assert source_connection.execute("SELECT relative_path FROM media_assets").fetchone()[0].startswith(str(source))
        assert target_connection.execute("SELECT relative_path FROM media_assets").fetchone()[0] == "/library/Images/image.jpg"
    finally:
        source_connection.close()
        target_connection.close()
