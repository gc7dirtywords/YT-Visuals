from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from yt_visuals.acquisition import ProbeResult
from yt_visuals.cli import cli
from yt_visuals.config import Settings
from yt_visuals.database import initialize_database
from yt_visuals.library import LibraryScanner, LibrarySearchFilters, get_library_status, search_library
from yt_visuals.library.inspection import inspect_media_file
from yt_visuals.models import MediaAsset, MediaLocation, MediaProvider, MediaSource


def make_image(path: Path, size: tuple[int, int] = (80, 40), color: str = "red") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path.read_bytes()


def test_scan_imports_image_metadata_relative_path_and_is_idempotent(
    catalog_settings: Settings,
) -> None:
    image_path = catalog_settings.root / "Library/Images/Nested/Factory.JPG"
    content = make_image(image_path, (320, 180))
    engine = initialize_database(catalog_settings)

    first = LibraryScanner(catalog_settings, engine).scan()
    assert (first.files_scanned, first.new_assets, first.error_count) == (1, 1, 0)
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.relative_path == "Library/Images/Nested/Factory.JPG"
        assert asset.media_type == "image"
        assert asset.mime_type == "image/jpeg"
        assert asset.file_size_bytes == len(content)
        assert asset.sha256 == hashlib.sha256(content).hexdigest()
        assert (asset.width, asset.height, asset.duration_ms) == (320, 180, None)
        assert asset.file_modified_at is not None
        assert asset.technical_metadata["local_file"]["filename"] == "Factory.JPG"
        assert asset.technical_metadata["local_file"]["extension"] == ".jpg"
        assert len(asset.locations) == 1
        location = asset.locations[0]
        assert location.relative_path == asset.relative_path
        assert location.provenance_type == "local_import"
        assert location.status == "available"

    second = LibraryScanner(
        catalog_settings,
        engine,
        inspector=lambda candidate: pytest.fail("unchanged file was rehashed"),
    ).scan()
    assert second.new_assets == 0
    assert second.unchanged_files == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaLocation)) == 1
    engine.dispose()


def test_video_scan_uses_ffprobe_metadata(catalog_settings: Settings) -> None:
    video_path = catalog_settings.root / "Library/Videos/clip.mp4"
    video_path.write_bytes(b"synthetic video bytes")
    engine = initialize_database(catalog_settings)

    def inspector(candidate):
        return inspect_media_file(
            candidate,
            video_probe=lambda path: ProbeResult(
                width=1920,
                height=1080,
                duration_ms=12_345,
                raw_metadata={"streams": [{"codec_name": "h264"}], "format": {"size": "21"}},
            ),
        )

    summary = LibraryScanner(catalog_settings, engine, inspector=inspector).scan()
    assert summary.error_count == 0
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.mime_type == "video/mp4"
        assert (asset.width, asset.height, asset.duration_ms) == (1920, 1080, 12_345)
        assert asset.technical_metadata["local_file"]["inspection"]["tool"] == "ffprobe"
        assert asset.technical_metadata["local_file"]["inspection"]["ffprobe"]["streams"][0]["codec_name"] == "h264"
    engine.dispose()


def test_duplicate_copy_move_missing_and_restore(catalog_settings: Settings) -> None:
    first_path = catalog_settings.root / "Library/Images/first.png"
    copy_path = catalog_settings.root / "Library/Images/copy.png"
    moved_path = catalog_settings.root / "Library/Images/moved.png"
    make_image(first_path, (40, 80))
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()

    shutil.copy2(first_path, copy_path)
    copied = LibraryScanner(catalog_settings, engine).scan()
    assert copied.duplicate_hashes == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        assert session.scalar(select(func.count()).select_from(MediaLocation)) == 2

    first_path.unlink()
    copy_path.replace(moved_path)
    moved = LibraryScanner(catalog_settings, engine).scan()
    assert moved.moved_paths == 1
    assert moved.missing_assets == 0
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.relative_path == "Library/Images/moved.png"
        assert asset.status == "active"
        assert {item.status for item in asset.locations} == {"available", "missing"}

    moved_path.unlink()
    missing = LibraryScanner(catalog_settings, engine).scan()
    assert missing.missing_assets == 1
    with Session(engine) as session:
        assert session.scalar(select(MediaAsset.status)) == "missing"

    make_image(moved_path, (40, 80))
    restored = LibraryScanner(catalog_settings, engine).scan()
    assert restored.restored_paths == 1
    with Session(engine) as session:
        assert session.scalar(select(MediaAsset.status)) == "active"
        assert session.scalar(
            select(MediaLocation.status).where(MediaLocation.relative_path == "Library/Images/moved.png")
        ) == "available"
    engine.dispose()


def test_dry_run_does_not_mutate_database(catalog_settings: Settings) -> None:
    make_image(catalog_settings.root / "Library/Images/planned.webp")
    engine = initialize_database(catalog_settings)
    summary = LibraryScanner(catalog_settings, engine).scan(dry_run=True)
    assert summary.dry_run is True
    assert summary.new_assets == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
        assert session.scalar(select(func.count()).select_from(MediaLocation)) == 0
    engine.dispose()


def test_changed_bytes_at_single_known_path_update_without_duplicate(
    catalog_settings: Settings,
) -> None:
    path = catalog_settings.root / "Library/Images/change.png"
    original = make_image(path, color="red")
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    replacement = make_image(path, color="blue")
    assert replacement != original

    summary = LibraryScanner(catalog_settings, engine).scan()
    assert summary.updated_files == 1
    assert summary.error_count == 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert asset.sha256 == hashlib.sha256(replacement).hexdigest()
    engine.dispose()


def test_corrupt_file_reports_error_and_scan_continues(catalog_settings: Settings) -> None:
    (catalog_settings.root / "Library/Images/bad.jpg").write_bytes(b"not an image")
    make_image(catalog_settings.root / "Library/Images/good.png")
    engine = initialize_database(catalog_settings)
    summary = LibraryScanner(catalog_settings, engine).scan()
    assert summary.files_scanned == 2
    assert summary.new_assets == 1
    assert summary.error_count == 1
    assert summary.errors[0].relative_path == "Library/Images/bad.jpg"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(MediaAsset)) == 1
    engine.dispose()


def test_video_probe_and_individual_inspection_failures_are_isolated(
    catalog_settings: Settings,
) -> None:
    bad_video = catalog_settings.root / "Library/Videos/bad.mp4"
    bad_video.write_bytes(b"bad video")
    make_image(catalog_settings.root / "Library/Images/good.png")
    engine = initialize_database(catalog_settings)

    def inspector(candidate):
        if candidate.media_type == "video":
            return inspect_media_file(
                candidate,
                video_probe=lambda path: ProbeResult(warning="ffprobe returned 1: invalid data"),
            )
        return inspect_media_file(candidate)

    summary = LibraryScanner(catalog_settings, engine, inspector=inspector).scan()
    assert summary.new_assets == 1
    assert summary.error_count == 1
    assert "ffprobe returned 1" in summary.errors[0].message
    engine.dispose()


def test_scanner_does_not_follow_symlinks_outside_library(catalog_settings: Settings) -> None:
    outside = catalog_settings.root / "outside"
    make_image(outside / "secret.png")
    link = catalog_settings.root / "Library/Images/external"
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip(f"directory junctions unavailable: {completed.stderr or completed.stdout}")
    else:
        os.symlink(outside, link, target_is_directory=True)
    engine = initialize_database(catalog_settings)
    try:
        summary = LibraryScanner(catalog_settings, engine).scan()
        assert summary.files_scanned == 0
        assert summary.skipped_symlinks == 1
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(MediaAsset)) == 0
    finally:
        engine.dispose()
        if os.name == "nt" and link.exists():
            link.rmdir()


def test_local_copy_matches_provider_asset_without_losing_provenance(
    catalog_settings: Settings,
) -> None:
    content = make_image(catalog_settings.root / "Library/Images/provider-original.png", (64, 32))
    copy_path = catalog_settings.root / "Library/Images/local-copy.png"
    copy_path.write_bytes(content)
    engine = initialize_database(catalog_settings)
    with Session(engine) as session:
        provider = MediaProvider(name="pexels")
        asset = MediaAsset(
            relative_path="Library/Images/provider-original.png",
            media_type="image",
            mime_type="image/png",
            file_size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            width=64,
            height=32,
        )
        asset.sources.append(
            MediaSource(
                provider=provider,
                provider_asset_id="photo:77",
                source_url="https://www.pexels.com/photo/77/",
                creator_name="Creator",
            )
        )
        session.add(asset)
        session.commit()

    summary = LibraryScanner(catalog_settings, engine).scan()
    assert summary.duplicate_hashes == 1
    with Session(engine) as session:
        asset = session.scalar(select(MediaAsset))
        assert asset is not None
        assert len(asset.sources) == 1
        assert asset.sources[0].provider.name == "pexels"
        assert len(asset.locations) == 2
        serialized = json.dumps(asset.technical_metadata).lower()
        assert "api_key" not in serialized
        assert "authorization" not in serialized
    engine.dispose()


def test_status_search_filters_and_cli_json(catalog_settings: Settings, capsys) -> None:
    make_image(catalog_settings.root / "Library/Images/factory-landscape.png", (120, 60))
    make_image(catalog_settings.root / "Library/Images/portrait.png", (40, 80))
    engine = initialize_database(catalog_settings)
    LibraryScanner(catalog_settings, engine).scan()
    with Session(engine) as session:
        landscape = session.scalar(
            select(MediaAsset).where(MediaAsset.relative_path.like("%factory-landscape%"))
        )
        assert landscape is not None
        landscape.sources.append(
            MediaSource(provider=MediaProvider(name="pexels"), provider_asset_id="photo:9", creator_name="Alex")
        )
        session.commit()

    results = search_library(
        engine,
        "factory",
        LibrarySearchFilters(
            media_type="image", orientation="landscape", usage="unused", provider="PEXELS"
        ),
    )
    assert len(results) == 1
    assert results[0].orientation == "landscape"
    assert results[0].providers == ("pexels",)
    status = get_library_status(engine)
    assert (status.total_assets, status.images, status.unused_assets) == (2, 2, 2)
    engine.dispose()

    assert cli(["library", "status", "--json"], settings=catalog_settings) == 0
    status_json = json.loads(capsys.readouterr().out)
    assert status_json["total_assets"] == 2
    assert cli(
        ["library", "search", "factory", "--orientation", "landscape", "--unused", "--provider", "pexels", "--json"],
        settings=catalog_settings,
    ) == 0
    search_json = json.loads(capsys.readouterr().out)
    assert len(search_json) == 1
    assert search_json[0]["relative_path"].endswith("factory-landscape.png")


def test_cli_scan_summary(catalog_settings: Settings, capsys) -> None:
    make_image(catalog_settings.root / "Library/Images/cli.png")
    assert cli(["library", "scan"], settings=catalog_settings) == 0
    output = capsys.readouterr().out
    assert "scanned 1 supported file(s)" in output
    assert "1 new" in output
