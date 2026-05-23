from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from .bundle import read_bundle, write_bundle
from .db import connect_mysql
from .porter import (
    LIVE_IMPORT_GUID_GAP,
    PorterError,
    checkout_character,
    create_import_plan,
    describe_plan,
    export_character,
    import_character,
    purge_character,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="acchar", description="Export/import AzerothCore WotLK characters.")
    subcommands = parser.add_subparsers(dest="command", required=True)

    export = subcommands.add_parser("export", help="Export one offline character to a JSON bundle.")
    add_db_args(export)
    selector = export.add_mutually_exclusive_group(required=True)
    selector.add_argument("--guid", type=int, help="Source character GUID.")
    selector.add_argument("--character", "--name", dest="character", help="Source character name.")
    export.add_argument("--account", type=int, help="Optional source account id, useful when selecting by name.")
    export.add_argument("--out", required=True, help="Output .acchar.json path.")
    export.add_argument("--checkout", action="store_true", help="After export, park the source character on a holding account.")
    export.add_argument("--holding-account", type=int, help="Account id used to hold checked-out characters.")
    export.set_defaults(func=run_export)

    inspect = subcommands.add_parser("inspect", help="Show what is inside a bundle.")
    inspect.add_argument("bundle")
    inspect.set_defaults(func=run_inspect)

    importer = subcommands.add_parser("import", help="Import a bundle into this server with new local GUIDs.")
    add_db_args(importer)
    importer.add_argument("--bundle", required=True)
    importer.add_argument("--account", required=True, type=int, help="Destination account id.")
    importer.add_argument("--name", help="Destination character name. Defaults to original name.")
    importer.add_argument("--dry-run", action="store_true", help="Plan and execute inside a rollback-only transaction.")
    importer.add_argument(
        "--worldserver-stopped",
        action="store_true",
        help="Confirm the destination worldserver is stopped for this real import.",
    )
    importer.add_argument(
        "--allow-live-import",
        action="store_true",
        help="Allow a real import while worldserver is running by allocating GUIDs with a large guard gap.",
    )
    importer.add_argument(
        "--guid-gap",
        default=LIVE_IMPORT_GUID_GAP,
        type=int,
        help=f"GUID guard gap for --allow-live-import. Default: {LIVE_IMPORT_GUID_GAP}.",
    )
    importer.set_defaults(func=run_import)

    purge = subcommands.add_parser("purge", help="Hard-delete a local parked character copy by GUID.")
    add_db_args(purge)
    purge.add_argument("--guid", required=True, type=int, help="Local character GUID to purge.")
    purge.add_argument("--expected-name", help="Optional safety check: abort unless the current DB name matches.")
    purge.add_argument("--yes", action="store_true", help="Actually delete rows. Without this, purge runs as a dry-run.")
    purge.set_defaults(func=run_purge)

    return parser


def add_db_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default=3306, type=int)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", help="Database password. If omitted, prompt securely.")
    parser.add_argument("--database", default="acore_characters")


def password_from_args(args: argparse.Namespace) -> str:
    if args.password is not None:
        return args.password
    return getpass.getpass("Database password: ")


def open_connection(args: argparse.Namespace):
    return connect_mysql(
        host=args.host,
        port=args.port,
        user=args.user,
        password=password_from_args(args),
        database=args.database,
    )


def run_export(args: argparse.Namespace) -> int:
    if args.checkout and args.holding_account is None:
        raise PorterError("--checkout requires --holding-account")

    conn = open_connection(args)
    try:
        bundle = export_character(conn, guid=args.guid, name=args.character, account=args.account)
        write_bundle(args.out, bundle)
        source = bundle["source"]
        print(f"Exported {source['character_name']} guid={source['character_guid']} to {Path(args.out)}")
        print(table_summary(bundle))
        if args.checkout:
            result = checkout_character(conn, guid=int(source["character_guid"]), holding_account=args.holding_account)
            print(
                "Checked out local character: "
                f"{result.original_name} guid={result.guid} moved from account={result.original_account} "
                f"to holding_account={result.holding_account} as {result.parked_name}"
            )
        return 0
    finally:
        conn.close()


def run_inspect(args: argparse.Namespace) -> int:
    bundle = read_bundle(args.bundle)
    source = bundle["source"]
    print(f"Bundle: {args.bundle}")
    print(f"Character: {source['character_name']} guid={source['character_guid']} account={source['account']}")
    print(f"Created: {bundle.get('created_at')}")
    print(table_summary(bundle))
    if bundle.get("skipped"):
        print("Skipped:")
        for table, reason in sorted(bundle["skipped"].items()):
            print(f"  {table}: {reason}")
    return 0


def run_import(args: argparse.Namespace) -> int:
    bundle = read_bundle(args.bundle)
    if args.worldserver_stopped and args.allow_live_import:
        raise PorterError("Use either --worldserver-stopped or --allow-live-import, not both")
    if args.guid_gap < 0:
        raise PorterError("--guid-gap must be zero or greater")
    if not args.dry_run and not args.worldserver_stopped and not args.allow_live_import:
        raise PorterError(
            "Refusing real import unless --worldserver-stopped or --allow-live-import is provided. "
            "Direct item GUID inserts can collide with a running worldserver."
        )
    conn = open_connection(args)
    try:
        if args.dry_run:
            plan = create_import_plan(
                conn,
                bundle,
                target_account=args.account,
                target_name=args.name,
                live_import=args.allow_live_import,
                guid_gap=args.guid_gap if args.allow_live_import else 0,
            )
            print("Dry-run plan:")
            print(describe_plan(plan))
            import_character(
                conn,
                bundle,
                target_account=args.account,
                target_name=args.name,
                dry_run=True,
                live_import=args.allow_live_import,
                guid_gap=args.guid_gap if args.allow_live_import else 0,
            )
            print("Dry-run insert completed and rolled back.")
        else:
            plan = import_character(
                conn,
                bundle,
                target_account=args.account,
                target_name=args.name,
                live_import=args.allow_live_import,
                guid_gap=args.guid_gap if args.allow_live_import else 0,
            )
            print("Imported character:")
            print(describe_plan(plan))
            if args.allow_live_import:
                print(
                    "Live import used a GUID guard gap. Restart the worldserver at the next convenient maintenance "
                    "window so its in-memory GUID counters resync from the database."
                )
        return 0
    finally:
        conn.close()


def run_purge(args: argparse.Namespace) -> int:
    conn = open_connection(args)
    try:
        result = purge_character(
            conn,
            guid=args.guid,
            expected_name=args.expected_name,
            dry_run=not args.yes,
        )
        action = "Purged" if args.yes else "Dry-run purge"
        print(f"{action}: guid={result.guid} name={result.name} items={result.item_count}")
        print("Rows: " + ", ".join(f"{table}={count}" for table, count in sorted(result.deleted_counts.items())))
        if not args.yes:
            print("No rows were deleted. Re-run with --yes to commit.")
        return 0
    finally:
        conn.close()


def table_summary(bundle: dict) -> str:
    parts = [f"{table}={len(rows)}" for table, rows in sorted(bundle["tables"].items())]
    return "Rows: " + ", ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except PorterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
