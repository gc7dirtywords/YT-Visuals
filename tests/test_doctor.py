from __future__ import annotations

from yt_visuals.config import Settings
from yt_visuals.doctor import all_checks_pass, run_doctor


def test_doctor_passes_with_expected_environment(catalog_settings: Settings) -> None:
    def available_tool(name: str) -> tuple[bool, str]:
        return True, f"{name} test executable"

    results = run_doctor(catalog_settings, tool_probe=available_tool)

    assert all_checks_pass(results)
    assert {result.name for result in results} >= {
        "database",
        "migrations",
        "ffmpeg",
        "ffprobe",
        "directory:Library/Images",
        "directory:Library/Videos",
    }


def test_doctor_reports_a_missing_expected_directory(catalog_settings: Settings) -> None:
    (catalog_settings.root / "Tools").rmdir()
    results = run_doctor(catalog_settings, tool_probe=lambda name: (True, name))

    tools_result = next(result for result in results if result.name == "directory:Tools")
    assert tools_result.ok is False
    assert all_checks_pass(results) is False

