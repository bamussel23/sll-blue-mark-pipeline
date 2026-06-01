"""CLI script to migrate Blue Mark Report files into a SQLite database.

Walks the Blue Mark Reports/ directory tree, parses all .ods and .xlsx
report files, and bulk-inserts the normalized records into the blue_mark.db
SQLite database.

Usage:
    python scripts/migrate_blue_marks.py
    python scripts/migrate_blue_marks.py --reports-dir "/path/to/Blue Mark Reports"
    python scripts/migrate_blue_marks.py --db-path /path/to/blue_mark.db --verbose
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add parent to path so stresscon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stresscon.blue_mark_db import BlueMarkDB
from stresscon.blue_mark_parser import parse_file

logger = logging.getLogger(__name__)

# Supported spreadsheet extensions
SUPPORTED_EXTENSIONS: set[str] = {".ods", ".xlsx"}

# Pattern to detect duplicate files, e.g. "12th(1).ods"
DUPLICATE_MARKER = "(1)"


def discover_report_files(reports_dir: Path) -> list[Path]:
    """Walk the reports directory and return sorted list of report files.

    Skips files containing '(1)' in the filename (duplicate copies).

    Args:
        reports_dir: Root directory containing year/month/file structure.

    Returns:
        Sorted list of Path objects for each report file to process.
    """
    files: list[Path] = []
    for path in sorted(reports_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if DUPLICATE_MARKER in path.stem:
            logger.debug("Skipping duplicate: %s", path)
            continue
        files.append(path)
    return files


def resolve_reports_dir(cli_path: str | None) -> Path:
    """Resolve the Blue Mark Reports directory.

    If a path is provided via CLI, use it directly. Otherwise, walk up from
    the script location looking for a 'Blue Mark Reports' directory.

    Args:
        cli_path: Optional explicit path from --reports-dir argument.

    Returns:
        Resolved Path to the reports directory.

    Raises:
        SystemExit: If the directory cannot be found.
    """
    if cli_path:
        p = Path(cli_path).resolve()
        if not p.is_dir():
            print(f"Error: Reports directory not found: {p}", file=sys.stderr)
            sys.exit(1)
        return p

    # Auto-detect: look relative to script, project root, and cwd
    candidates = [
        Path(__file__).resolve().parent.parent.parent / "Blue Mark Reports",
        Path(__file__).resolve().parent.parent / "Blue Mark Reports",
        Path.cwd() / "Blue Mark Reports",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    print(
        "Error: Could not auto-detect 'Blue Mark Reports/' directory.\n"
        "       Use --reports-dir to specify the path explicitly.",
        file=sys.stderr,
    )
    sys.exit(1)


def resolve_db_path(cli_path: str | None) -> Path:
    """Resolve the SQLite database path.

    Args:
        cli_path: Optional explicit path from --db-path argument.

    Returns:
        Resolved Path for the database file.
    """
    if cli_path:
        return Path(cli_path).resolve()
    # Default: data/blue_mark.db relative to the python/ directory
    return Path(__file__).resolve().parent.parent / "data" / "blue_mark.db"


def format_relative_path(file_path: Path, base_dir: Path) -> str:
    """Return a short relative path string for display purposes."""
    try:
        return str(file_path.relative_to(base_dir))
    except ValueError:
        return str(file_path)


def run_migration(
    reports_dir: Path,
    db_path: Path,
    verbose: bool = False,
) -> dict[str, int]:
    """Execute the full migration pipeline.

    Args:
        reports_dir: Root directory with Blue Mark Report files.
        db_path: Path to the SQLite database.
        verbose: If True, enable debug-level logging.

    Returns:
        Dict with migration statistics: files_processed, files_skipped,
        files_errored, total_records_inserted.
    """
    # Discover files
    all_files = list(reports_dir.rglob("*"))
    skipped_dupes = [
        f for f in all_files
        if f.is_file()
        and f.suffix.lower() in SUPPORTED_EXTENSIONS
        and DUPLICATE_MARKER in f.stem
    ]
    report_files = discover_report_files(reports_dir)

    total_files = len(report_files)
    print(f"Found {total_files} report files in {reports_dir}")
    if skipped_dupes:
        print(f"Skipping {len(skipped_dupes)} duplicate file(s) with '{DUPLICATE_MARKER}' in name")
    print()

    if total_files == 0:
        print("No report files found. Nothing to migrate.")
        return {
            "files_processed": 0,
            "files_skipped": len(skipped_dupes),
            "files_errored": 0,
            "total_records_inserted": 0,
        }

    # Open database
    db = BlueMarkDB(db_path)
    db.connect()

    files_processed = 0
    files_errored = 0
    total_records_inserted = 0
    error_log: list[tuple[str, str]] = []

    start_time = time.monotonic()

    try:
        for idx, file_path in enumerate(report_files, start=1):
            rel_path = format_relative_path(file_path, reports_dir)

            try:
                records = parse_file(file_path)
                inserted = db.bulk_insert(records)
                total_records_inserted += inserted
                files_processed += 1

                print(f"Processing [{idx}/{total_files}] {rel_path} ... {inserted} records")

                if verbose and inserted != len(records):
                    dupes = len(records) - inserted
                    logger.debug(
                        "  %d duplicate record(s) skipped for %s", dupes, rel_path
                    )

            except Exception as exc:
                files_errored += 1
                error_msg = f"{type(exc).__name__}: {exc}"
                error_log.append((rel_path, error_msg))
                logger.error("Failed to process %s: %s", rel_path, error_msg)
                print(f"Processing [{idx}/{total_files}] {rel_path} ... ERROR: {error_msg}")

        elapsed = time.monotonic() - start_time

        # Print summary
        print()
        print("=" * 60)
        print("  Migration Summary")
        print("=" * 60)
        print(f"  Time elapsed:        {elapsed:.1f}s")
        print(f"  Files processed:     {files_processed}")
        print(f"  Files skipped:       {len(skipped_dupes)} (duplicates)")
        print(f"  Files with errors:   {files_errored}")
        print(f"  Records inserted:    {total_records_inserted}")

        # Print error details if any
        if error_log:
            print()
            print("  Errors:")
            for rel_path, msg in error_log:
                print(f"    - {rel_path}: {msg}")

        # Print database stats
        stats = db.get_summary_stats()
        print()
        print("=" * 60)
        print("  Database Stats")
        print("=" * 60)
        print(f"  Total records:       {stats['total_records']}")
        print(f"  Unique jobs:         {stats['unique_jobs']}")
        print(f"  Unique pieces:       {stats['unique_pieces']}")
        if stats["date_range"][0] and stats["date_range"][1]:
            print(f"  Date range:          {stats['date_range'][0]} to {stats['date_range'][1]}")
        if stats["by_schema"]:
            print(f"  By schema version:   {stats['by_schema']}")
        print(f"  Database path:       {db_path}")
        print()

    finally:
        db.close()

    return {
        "files_processed": files_processed,
        "files_skipped": len(skipped_dupes),
        "files_errored": files_errored,
        "total_records_inserted": total_records_inserted,
    }


def main() -> None:
    """CLI entry point for the Blue Mark Reports migration script."""
    parser = argparse.ArgumentParser(
        description="Migrate Blue Mark Report files (.ods/.xlsx) into a SQLite database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/migrate_blue_marks.py\n"
            '  python scripts/migrate_blue_marks.py --reports-dir "/path/to/Blue Mark Reports"\n'
            "  python scripts/migrate_blue_marks.py --db-path ./my_db.sqlite --verbose\n"
        ),
    )
    parser.add_argument(
        "--reports-dir",
        type=str,
        default=None,
        help=(
            "Path to the 'Blue Mark Reports/' root directory. "
            "If omitted, auto-detects relative to the script location."
        ),
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the SQLite database file (default: data/blue_mark.db).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging output.",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    reports_dir = resolve_reports_dir(args.reports_dir)
    db_path = resolve_db_path(args.db_path)

    print("=" * 60)
    print("  Blue Mark Reports Migration")
    print("=" * 60)
    print(f"  Reports dir: {reports_dir}")
    print(f"  Database:    {db_path}")
    print()

    result = run_migration(reports_dir, db_path, verbose=args.verbose)

    # Exit with error code if any files failed
    if result["files_errored"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
