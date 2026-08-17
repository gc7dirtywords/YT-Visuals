from __future__ import annotations

import argparse
import json
from collections.abc import Callable

from sqlalchemy import Engine

from .acquisition import AcquisitionOutcome, AcquisitionService
from .config import Settings
from .database import initialize_database
from .doctor import all_checks_pass, run_doctor
from .providers.base import MediaProvider, MediaSearchResult, SearchPage
from .providers.errors import ProviderError
from .providers.registry import create_provider, list_providers


ProviderFactory = Callable[[str, Settings], MediaProvider]
AcquisitionFactory = Callable[[Settings, Engine], AcquisitionService]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-visuals", description="Local YouTube visual asset catalog tools"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Verify directories, database, migrations, and media tools")

    database = subparsers.add_parser("db", help="Database maintenance")
    database_subparsers = database.add_subparsers(dest="database_command", required=True)
    database_subparsers.add_parser("upgrade", help="Create or migrate the catalog database")

    providers = subparsers.add_parser("providers", help="List available media providers")
    providers.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    search = subparsers.add_parser("search", help="Search a media provider without downloading")
    search.add_argument("provider", help="Provider name, such as pexels")
    search.add_argument("media_kind", choices=("photos", "videos"))
    search.add_argument("query")
    search.add_argument("--orientation", choices=("landscape", "portrait", "square"))
    search.add_argument("--size", choices=("large", "medium", "small"))
    search.add_argument("--color", help="Photo color name or #RRGGBB")
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--per-page", type=int, default=15)
    search.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    download = subparsers.add_parser("download", help="Download and catalog one provider asset")
    download.add_argument("provider", help="Provider name, such as pexels")
    download.add_argument("media_kind", choices=("photos", "videos"))
    download.add_argument("provider_asset_id")
    download.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    return parser


def cli(
    argv: list[str] | None = None,
    *,
    settings: Settings | None = None,
    provider_factory: ProviderFactory = create_provider,
    acquisition_factory: AcquisitionFactory = AcquisitionService,
) -> int:
    args = build_parser().parse_args(argv)
    settings = settings or Settings.load()

    try:
        if args.command == "doctor":
            results = run_doctor(settings)
            for result in results:
                marker = "OK" if result.ok else "FAIL"
                print(f"[{marker}] {result.name}: {result.detail}")
            return 0 if all_checks_pass(results) else 1

        if args.command == "db" and args.database_command == "upgrade":
            engine = initialize_database(settings)
            engine.dispose()
            print(f"Database is current: {settings.database_path}")
            return 0

        if args.command == "providers":
            registrations = list_providers(settings)
            if args.json:
                print(json.dumps([item.to_dict() for item in registrations], indent=2))
            else:
                for item in registrations:
                    state = "configured" if item.configured else "missing PEXELS_API_KEY"
                    print(f"{item.info.name}: {item.info.display_name} ({state})")
                    print(f"  Website: {item.info.website_url}")
                    print(f"  License: {item.info.license_name} - {item.info.license_url}")
            return 0

        if args.command == "search":
            return _search(args, settings, provider_factory)

        if args.command == "download":
            return _download(args, settings, provider_factory, acquisition_factory)
    except ProviderError as exc:
        print(f"Error: {exc}")
        return 1

    return 2


def _search(args: argparse.Namespace, settings: Settings, provider_factory: ProviderFactory) -> int:
    if args.media_kind == "videos" and args.color is not None:
        raise ProviderError("--color is supported only for photo searches")
    provider = provider_factory(args.provider, settings)
    try:
        common = {
            "orientation": args.orientation,
            "size": args.size,
            "page": args.page,
            "per_page": args.per_page,
        }
        if args.media_kind == "photos":
            page = provider.search_photos(args.query, color=args.color, **common)
        else:
            page = provider.search_videos(args.query, **common)
    finally:
        provider.close()

    if args.json:
        print(json.dumps(page.to_dict(), indent=2, ensure_ascii=False))
    else:
        _print_search_page(page, args.media_kind)
    return 0


def _download(
    args: argparse.Namespace,
    settings: Settings,
    provider_factory: ProviderFactory,
    acquisition_factory: AcquisitionFactory,
) -> int:
    engine = initialize_database(settings)
    service = acquisition_factory(settings, engine)
    media_type = "image" if args.media_kind == "photos" else "video"
    provider: MediaProvider | None = None
    try:
        existing = service.find_existing(args.provider, media_type, args.provider_asset_id)
        if existing is not None:
            outcome = existing
        else:
            provider = provider_factory(args.provider, settings)
            result = (
                provider.get_photo(args.provider_asset_id)
                if args.media_kind == "photos"
                else provider.get_video(args.provider_asset_id)
            )
            outcome = service.acquire(result)
    finally:
        if provider is not None:
            provider.close()
        service.close()
        engine.dispose()

    if args.json:
        print(json.dumps(outcome.to_dict(), indent=2))
    else:
        _print_acquisition(outcome)
    return 0


def _print_search_page(page: SearchPage, media_kind: str) -> None:
    print(
        f"Page {page.page}: {len(page.results)} result(s) shown "
        f"of {page.total_results} total"
    )
    if not page.results:
        print("No results.")
        return
    for result in page.results:
        dimensions = (
            f"{result.width}x{result.height}"
            if result.width is not None and result.height is not None
            else "dimensions unknown"
        )
        duration = (
            f", {result.duration_ms / 1000:g}s" if result.duration_ms is not None else ""
        )
        print(f"\n{result.provider_asset_id}: {result.title or '(untitled)'}")
        print(f"  {dimensions}{duration}; {result.mime_type or 'type unknown'}")
        print(f"  Creator: {result.creator_name or 'unknown'}")
        print(f"  Page: {result.source_url}")
        if result.preview_url:
            print(f"  Preview: {result.preview_url}")
        print(
            f"  Download: yt-visuals download {result.provider} {media_kind} "
            f"{result.provider_asset_id}"
        )


def _print_acquisition(outcome: AcquisitionOutcome) -> None:
    if outcome.duplicate_reason == "provider_asset":
        action = "Already cataloged (same provider asset)"
    elif outcome.duplicate_reason == "sha256":
        action = "Reused catalog asset (identical SHA-256); source metadata attached"
    else:
        action = "Downloaded and cataloged"
    print(f"{action}: asset {outcome.asset_id}")
    print(f"  Path: {outcome.relative_path}")
    print(f"  SHA-256: {outcome.sha256}")
    print(f"  Bytes: {outcome.file_size_bytes}")
    if outcome.download_history_id is not None:
        print(f"  Download history: {outcome.download_history_id}")


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()
