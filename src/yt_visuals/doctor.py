from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import text

from .config import EXPECTED_DIRECTORIES, Settings
from .database import get_migration_status, initialize_database


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


ToolProbe = Callable[[str], tuple[bool, str]]


def probe_media_tool(name: str) -> tuple[bool, str]:
    executable = shutil.which(name)
    if executable is None:
        return False, f"{name} was not found on PATH"
    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"{executable}: {exc}"
    first_line = (completed.stdout or completed.stderr).splitlines()
    detail = first_line[0] if first_line else executable
    return completed.returncode == 0, detail


def run_doctor(settings: Settings, tool_probe: ToolProbe = probe_media_tool) -> list[CheckResult]:
    results: list[CheckResult] = []
    for relative_path in EXPECTED_DIRECTORIES:
        path = settings.root / relative_path
        results.append(
            CheckResult(
                name=f"directory:{relative_path.as_posix()}",
                ok=path.is_dir(),
                detail=str(path) if path.is_dir() else f"missing directory: {path}",
            )
        )

    try:
        engine = initialize_database(settings)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            results.append(CheckResult("database", True, str(settings.database_path)))
            migration = get_migration_status(settings, connection)
            results.append(
                CheckResult(
                    "migrations",
                    migration.is_current,
                    f"current={migration.current_revision}, head={migration.head_revision}",
                )
            )
        engine.dispose()
    except Exception as exc:  # Doctor must report failures instead of hiding later checks.
        results.append(CheckResult("database", False, str(exc)))
        results.append(CheckResult("migrations", False, "not checked because database setup failed"))

    for tool in ("ffmpeg", "ffprobe"):
        ok, detail = tool_probe(tool)
        results.append(CheckResult(tool, ok, detail))

    return results


def all_checks_pass(results: list[CheckResult]) -> bool:
    return all(result.ok for result in results)

