from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MAX_IMAGE_DOWNLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_VIDEO_DOWNLOAD_BYTES = 500 * 1024 * 1024


EXPECTED_DIRECTORIES = (
    Path("Library"),
    Path("Library/Images"),
    Path("Library/Videos"),
    Path("Projects"),
    Path("Temp"),
    Path("Tools"),
)


def discover_root() -> Path:
    configured = os.environ.get("YT_VISUALS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path

    @classmethod
    def load(cls) -> "Settings":
        return cls(root=discover_root())

    @property
    def data_dir(self) -> Path:
        return self.root / "Data"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "catalog.sqlite3"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.database_path.resolve().as_posix()}"

    @property
    def alembic_ini(self) -> Path:
        return self.root / "alembic.ini"

    @property
    def migrations_dir(self) -> Path:
        return self.root / "migrations"

    @property
    def pexels_api_key(self) -> str | None:
        value = os.environ.get("PEXELS_API_KEY", "").strip()
        return value or None

    @property
    def max_image_download_bytes(self) -> int:
        return _positive_env_int(
            "YT_VISUALS_MAX_IMAGE_DOWNLOAD_BYTES", DEFAULT_MAX_IMAGE_DOWNLOAD_BYTES
        )

    @property
    def max_video_download_bytes(self) -> int:
        return _positive_env_int(
            "YT_VISUALS_MAX_VIDEO_DOWNLOAD_BYTES", DEFAULT_MAX_VIDEO_DOWNLOAD_BYTES
        )


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
