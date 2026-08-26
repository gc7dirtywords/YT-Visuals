from __future__ import annotations

from yt_visuals import cli as cli_module
from yt_visuals.config import Settings
from yt_visuals.producer.web import run_web_app


class FakeServer:
    server_port = 9123

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def serve_forever(self) -> None:
        self.events.append("serve")

    def server_close(self) -> None:
        self.events.append("close")


def test_server_binds_before_opening_one_browser(catalog_settings: Settings) -> None:
    events: list[str] = []

    def server_factory(host, port, app, threaded):
        events.append("bind")
        assert (host, port, threaded) == ("127.0.0.1", 8765, True)
        return FakeServer(events)

    run_web_app(
        catalog_settings,
        app_factory=lambda settings: object(),
        server_factory=server_factory,
        browser_opener=lambda url: events.append(f"browser:{url}"),
        output=lambda message: None,
    )

    assert events == ["bind", "browser:http://127.0.0.1:9123", "serve", "close"]


def test_no_browser_and_browser_failure_both_leave_server_running(
    catalog_settings: Settings,
) -> None:
    for open_browser in (False, True):
        events: list[str] = []
        output: list[str] = []

        def fail_browser(url: str) -> None:
            events.append("browser")
            raise OSError("no browser")

        run_web_app(
            catalog_settings,
            open_browser=open_browser,
            app_factory=lambda settings: object(),
            server_factory=lambda *args, **kwargs: FakeServer(events),
            browser_opener=fail_browser,
            output=output.append,
        )

        assert "serve" in events
        assert events.count("browser") == int(open_browser)
        if open_browser:
            assert any("Open http://127.0.0.1:9123" in line for line in output)


def test_non_loopback_binding_prints_warning_and_lan_url(catalog_settings: Settings) -> None:
    output: list[str] = []
    run_web_app(
        catalog_settings,
        host="0.0.0.0",
        open_browser=False,
        app_factory=lambda settings: object(),
        server_factory=lambda *args, **kwargs: FakeServer([]),
        output=output.append,
        lan_ip_resolver=lambda: "192.168.1.20",
    )

    assert any(line.startswith("WARNING:") for line in output)
    assert "LAN: http://192.168.1.20:9123" in output


def test_keyboard_interrupt_closes_server_cleanly(catalog_settings: Settings) -> None:
    events: list[str] = []

    class InterruptingServer(FakeServer):
        def serve_forever(self) -> None:
            self.events.append("interrupt")
            raise KeyboardInterrupt

    run_web_app(
        catalog_settings,
        open_browser=False,
        app_factory=lambda settings: object(),
        server_factory=lambda *args, **kwargs: InterruptingServer(events),
        output=lambda message: None,
    )

    assert events == ["interrupt", "close"]


def test_cli_no_browser_flag_is_forwarded(catalog_settings: Settings, monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_run(settings: Settings, **kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("yt_visuals.producer.web.run_web_app", fake_run)

    assert cli_module.cli(["web", "--no-browser"], settings=catalog_settings) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8765, "open_browser": False}]
