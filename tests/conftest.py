from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from yt_visuals.config import EXPECTED_DIRECTORIES, Settings


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog_settings(tmp_path: Path) -> Settings:
    for relative_path in EXPECTED_DIRECTORIES:
        (tmp_path / relative_path).mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPOSITORY_ROOT / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(REPOSITORY_ROOT / "migrations", tmp_path / "migrations")
    return Settings(root=tmp_path)

