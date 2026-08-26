from __future__ import annotations

from yt_visuals.config import Settings
from yt_visuals.doctor import all_checks_pass, run_doctor


def test_doctor_passes_with_expected_environment(catalog_settings: Settings, monkeypatch) -> None:
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setattr("yt_visuals.credentials.keyring.get_password", lambda *args: None)
    def available_tool(name: str) -> tuple[bool, str]:
        return True, f"{name} test executable"

    results = run_doctor(catalog_settings, tool_probe=available_tool)

    assert all_checks_pass(results)
    assert {result.name for result in results} >= {
        "provider:pexels",
        "database",
        "migrations",
        "ffmpeg",
        "ffprobe",
        "directory:Library/Images",
        "directory:Library/Videos",
    }
    provider = next(result for result in results if result.name == "provider:pexels")
    assert provider.ok is True
    assert provider.detail == "not configured; local-only workflows remain available"


def test_doctor_reports_pexels_configured_without_network(
    catalog_settings: Settings, monkeypatch
) -> None:
    monkeypatch.setenv("PEXELS_API_KEY", "test-placeholder")
    results = run_doctor(catalog_settings, tool_probe=lambda name: (True, name))
    provider = next(result for result in results if result.name == "provider:pexels")
    assert provider.ok is True
    assert provider.detail == "configured"


def test_doctor_reports_a_missing_expected_directory(catalog_settings: Settings) -> None:
    (catalog_settings.root / "Tools").rmdir()
    results = run_doctor(catalog_settings, tool_probe=lambda name: (True, name))

    tools_result = next(result for result in results if result.name == "directory:Tools")
    assert tools_result.ok is False
    assert all_checks_pass(results) is False
