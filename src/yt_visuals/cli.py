from __future__ import annotations

import argparse

from .config import Settings
from .database import initialize_database
from .doctor import all_checks_pass, run_doctor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-visuals", description="Local YouTube visual asset catalog tools"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Verify directories, database, migrations, and media tools")
    database = subparsers.add_parser("db", help="Database maintenance")
    database_subparsers = database.add_subparsers(dest="database_command", required=True)
    database_subparsers.add_parser("upgrade", help="Create or migrate the catalog database")
    return parser


def cli(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings.load()

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

    return 2


def main() -> None:
    raise SystemExit(cli())


if __name__ == "__main__":
    main()

