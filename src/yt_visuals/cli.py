from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from .acquisition import AcquisitionOutcome, AcquisitionService
from .config import Settings
from .database import initialize_database
from .doctor import all_checks_pass, run_doctor
from .library import LibraryScanner
from .providers.base import MediaProvider, MediaSearchResult, SearchPage
from .providers.errors import ProviderError
from .providers.registry import create_provider, list_providers
from .services import MediaCatalogService, MediaServiceError, SearchMediaRequest
from .workflow import VisualWorkflowError, VisualWorkflowService


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

    library = subparsers.add_parser("library", help="Scan and search the local media library")
    library_subparsers = library.add_subparsers(dest="library_command", required=True)
    library_scan = library_subparsers.add_parser("scan", help="Reconcile local files with the catalog")
    library_scan.add_argument("--dry-run", action="store_true", help="Inspect and report without database changes")
    library_scan.add_argument("--verbose", action="store_true", help="List individual scan actions")
    library_scan.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    library_status = library_subparsers.add_parser("status", help="Summarize the local catalog")
    library_status.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    library_search = library_subparsers.add_parser("search", help="Search cataloged local media")
    library_search.add_argument("query", nargs="?", default="")
    library_search.add_argument("--type", dest="media_type", choices=("image", "video"))
    library_search.add_argument("--orientation", choices=("landscape", "portrait", "square"))
    usage = library_search.add_mutually_exclusive_group()
    usage.add_argument("--unused", action="store_true")
    usage.add_argument("--used", action="store_true")
    library_search.add_argument("--missing", action="store_true")
    library_search.add_argument("--provider")
    library_search.add_argument("--mime")
    library_search.add_argument("--min-width", type=int)
    library_search.add_argument("--min-height", type=int)
    library_search.add_argument("--min-duration", type=float, help="Minimum video duration in seconds")
    library_search.add_argument("--max-duration", type=float, help="Maximum video duration in seconds")
    library_search.add_argument("--limit", type=int, default=100)
    library_search.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    visual = subparsers.add_parser("visual", help="Manage deterministic story visual review workflows")
    visual_subparsers = visual.add_subparsers(dest="visual_command", required=True)
    visual_request = visual_subparsers.add_parser("request", help="Validate Visual Request files")
    visual_request_subparsers = visual_request.add_subparsers(dest="visual_request_command", required=True)
    visual_validate = visual_request_subparsers.add_parser("validate", help="Validate a Visual Request v1 JSON file")
    visual_validate.add_argument("path")
    visual_validate.add_argument("--json", action="store_true", help="Print normalized machine-readable JSON")

    visual_workflow = visual_subparsers.add_parser("workflow", help="Run the local story review loop")
    visual_workflow_subparsers = visual_workflow.add_subparsers(dest="visual_workflow_command", required=True)
    workflow_start = visual_workflow_subparsers.add_parser("start", help="Start a workflow from a Visual Request")
    workflow_start.add_argument("path")
    workflow_start.add_argument("--json", action="store_true")
    workflow_revise = visual_workflow_subparsers.add_parser("revise", help="Import an explicit workflow revision")
    workflow_revise.add_argument("workflow_id")
    workflow_revise.add_argument("path")
    workflow_revise.add_argument("--json", action="store_true")
    workflow_source = visual_workflow_subparsers.add_parser("source", help="Generate the next local candidate package")
    workflow_source.add_argument("workflow_id")
    workflow_source.add_argument("--json", action="store_true")
    workflow_status = visual_workflow_subparsers.add_parser("status", help="Show workflow state")
    workflow_status.add_argument("workflow_id")
    workflow_status.add_argument("--json", action="store_true")
    workflow_review = visual_workflow_subparsers.add_parser("review", help="Import a completed Visual Review")
    workflow_review.add_argument("workflow_id")
    workflow_review.add_argument("path")
    workflow_review.add_argument("--json", action="store_true")
    workflow_artifacts = visual_workflow_subparsers.add_parser("artifacts", help="List append-only workflow artifacts")
    workflow_artifacts.add_argument("workflow_id")
    workflow_artifacts.add_argument("--json", action="store_true")
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

        if args.command == "library":
            return _library(args, settings)
        if args.command == "visual":
            return _visual(args, settings)
    except MediaServiceError as exc:
        print(f"Error [{exc.code}]: {exc}")
        return 1
    except ValidationError as exc:
        first = exc.errors(include_url=False)[0]
        field = ".".join(str(item) for item in first["loc"])
        print(f"Error [invalid_filter]: {field}: {first['msg']}")
        return 1
    except (ProviderError, SQLAlchemyError, OSError, RuntimeError) as exc:
        print(f"Error: {exc}")
        return 1

    return 2


def _visual(args: argparse.Namespace, settings: Settings) -> int:
    if args.visual_command == "request" and args.visual_request_command == "validate":
        request = VisualWorkflowService.validate_request_file(Path(args.path))
        if args.json:
            print(request.model_dump_json(indent=2))
        else:
            print(
                f"Valid Visual Request v1: {request.story.story_id}; "
                f"{len(request.beats)} beat(s)"
            )
        return 0

    engine = initialize_database(settings)
    service = VisualWorkflowService(settings, engine)
    try:
        command = args.visual_workflow_command
        if command == "start":
            result = service.start_workflow(Path(args.path)).to_dict()
        elif command == "revise":
            result = service.revise_workflow(args.workflow_id, Path(args.path)).to_dict()
        elif command == "source":
            result = service.generate_package(args.workflow_id).to_dict()
        elif command == "status":
            result = service.get_status(args.workflow_id)
        elif command == "review":
            result = service.import_review(args.workflow_id, Path(args.path)).to_dict()
        elif command == "artifacts":
            result = {"workflow_id": args.workflow_id, "packages": service.get_artifacts(args.workflow_id)}
        else:
            return 2
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    finally:
        engine.dispose()


def _library(args: argparse.Namespace, settings: Settings) -> int:
    engine = initialize_database(settings)
    service = MediaCatalogService(engine)
    try:
        if args.library_command == "scan":
            summary = LibraryScanner(settings, engine).scan(
                dry_run=args.dry_run, verbose=args.verbose
            )
            if args.json:
                print(json.dumps(summary.to_dict(), indent=2))
            else:
                prefix = "Dry run; " if summary.dry_run else ""
                print(
                    f"{prefix}scanned {summary.files_scanned} supported file(s): "
                    f"{summary.new_assets} new, {summary.existing_assets} existing, "
                    f"{summary.duplicate_hashes} duplicate hash(es), "
                    f"{summary.moved_paths} moved path(s), {summary.missing_assets} missing asset(s), "
                    f"{summary.error_count} error(s)."
                )
                if args.verbose:
                    for action in summary.actions:
                        print(f"  {action}")
                for error in summary.errors:
                    print(f"  ERROR {error.relative_path}: {error.category}: {error.message}")
            return 1 if summary.error_count else 0

        if args.library_command == "status":
            status = service.get_library_status()
            if args.json:
                print(json.dumps(_legacy_status_dict(status), indent=2))
            else:
                print(
                    f"Assets: {status.total_assets} total, {status.available_assets} active, "
                    f"{status.missing_assets} missing, {status.unused_assets} unused"
                )
                print(f"Media: {status.images} image(s), {status.videos} video(s)")
                print(
                    f"Locations: {status.available_locations} available, "
                    f"{status.missing_locations} missing, "
                    f"{status.duplicate_physical_locations} duplicate copy/copies"
                )
                print(f"Available bytes: {status.total_available_bytes}")
            return 0

        usage = "unused" if args.unused else "used" if args.used else None
        request = SearchMediaRequest(
            query=args.query,
            media_type=args.media_type,
            orientation=args.orientation,
            usage=usage,
            availability="missing" if args.missing else "available",
            provider=args.provider,
            mime_type=args.mime,
            min_width=args.min_width,
            min_height=args.min_height,
            min_duration_ms=_seconds_to_ms(args.min_duration),
            max_duration_ms=_seconds_to_ms(args.max_duration),
            limit=args.limit,
        )
        results = service.search_media(request).candidates
        if args.json:
            print(json.dumps([_legacy_search_dict(item) for item in results], indent=2))
        else:
            print(f"{len(results)} catalog result(s).")
            for item in results:
                dimensions = (
                    f"{item.width}x{item.height}" if item.width and item.height else "dimensions unknown"
                )
                duration = f", {item.duration_ms / 1000:g}s" if item.duration_ms is not None else ""
                print(f"\n{item.asset_id}: {item.relative_path}")
                print(f"  {item.media_type}; {item.mime_type or 'MIME unknown'}; {dimensions}{duration}")
                status = "active" if item.available else "missing"
                print(f"  {status}; used {item.usage_count} time(s); SHA-256 {item.sha256 or 'unknown'}")
                if item.providers:
                    print(f"  Providers: {', '.join(item.providers)}")
                if len(item.locations) > 1:
                    print(f"  Locations: {', '.join(item.locations)}")
        return 0
    finally:
        engine.dispose()


def _legacy_status_dict(status) -> dict[str, object]:
    return {
        "total_assets": status.total_assets,
        "active_assets": status.available_assets,
        "missing_assets": status.missing_assets,
        "images": status.images,
        "videos": status.videos,
        "available_locations": status.available_locations,
        "missing_locations": status.missing_locations,
        "duplicate_locations": status.duplicate_physical_locations,
        "unused_assets": status.unused_assets,
        "total_bytes": status.total_available_bytes,
    }


def _legacy_search_dict(item) -> dict[str, object]:
    return {
        "id": item.asset_id,
        "relative_path": item.relative_path,
        "locations": list(item.locations),
        "media_type": item.media_type,
        "mime_type": item.mime_type,
        "width": item.width,
        "height": item.height,
        "duration_ms": item.duration_ms,
        "orientation": item.orientation,
        "status": "active" if item.available else "missing",
        "sha256": item.sha256,
        "usage_count": item.usage_count,
        "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
        "providers": list(item.providers),
        "creators": list(item.creators),
        "tags": list(item.tags),
    }


def _seconds_to_ms(value: float | None) -> int | None:
    if value is None:
        return None
    if value < 0:
        raise ProviderError("duration filters must be nonnegative")
    return round(value * 1000)


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
