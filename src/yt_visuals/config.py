from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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

