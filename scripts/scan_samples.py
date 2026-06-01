"""CLI script to scan audio samples and catalog them in SQLite.

Walks the samples directory tree, analyzes each audio file with librosa,
and stores the extracted metadata in a SQLite database for querying and
dashboard visualization.

Usage:
    python scripts/scan_samples.py
    python scripts/scan_samples.py --samples-dir ~/Music/Samples
    python scripts/scan_samples.py --force-rescan --verbose
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Add parent to path so stresscon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stresscon.sample_db import SampleDB
from stresscon.sample_analyzer import analyze_file

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS: set[str] = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}


def discover_audio_files(samples_dir: Path) -> list[Path]:
    """Recursively find all audio files. Returns sorted list."""
    files: list[Path] = []
    for path in sorted(samples_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if path.name.startswith("."):
            continue
        files.append(path)
    return files


def run_scan(
    samples_dir: Path,
    db_path: Path,
    force_rescan: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Execute the full scan pipeline.

    Returns dict with scan statistics.
    """
    # Discover files
    audio_files = discover_audio_files(samples_dir)
    total_files = len(audio_files)
    print(f"Found {total_files} audio files in {samples_dir}")
    print()

    if total_files == 0:
        print("No audio files found. Nothing to scan.")
        return {"files_scanned": 0, "files_skipped": 0, "files_errored": 0}

    db = SampleDB(db_path)
    db.connect()

    try:
        # Determine which files to skip (already scanned)
        if force_rescan:
            already_scanned: set[str] = set()
            print("Force rescan enabled — re-analyzing all files")
        else:
            already_scanned = db.get_scanned_paths()
            if already_scanned:
                print(f"Skipping {len(already_scanned)} already-scanned files")
        print()

        files_scanned = 0
        files_skipped = 0
        files_errored = 0
        batch: list[dict] = []
        error_log: list[tuple[str, str]] = []

        start_time = time.monotonic()

        for idx, file_path in enumerate(audio_files, start=1):
            abs_path = str(file_path.resolve())

            if abs_path in already_scanned:
                files_skipped += 1
                if verbose:
                    logger.debug("Skipping (already scanned): %s", file_path.name)
                continue

            print(f"Analyzing [{idx}/{total_files}] {file_path.name} ...", end=" ")

            result = analyze_file(file_path)

            if "error" in result:
                files_errored += 1
                error_log.append((file_path.name, result["error"]))
                print(f"ERROR: {result['error']}")
                continue

            batch.append(result)
            files_scanned += 1

            bpm_str = f"{result['bpm']} BPM" if result.get("bpm") else "no BPM"
            key_str = result.get("musical_key") or "no key"
            print(f"{result['category']} / {result['sample_type']} / {bpm_str} / {key_str}")

            # Flush batch every 50 files to avoid memory buildup
            if len(batch) >= 50:
                db.bulk_insert(batch)
                batch.clear()

        # Insert remaining batch
        if batch:
            db.bulk_insert(batch)

        elapsed = time.monotonic() - start_time

        # Print summary
        print()
        print("=" * 60)
        print("  Scan Summary")
        print("=" * 60)
        print(f"  Time elapsed:        {elapsed:.1f}s")
        print(f"  Files scanned:       {files_scanned}")
        print(f"  Files skipped:       {files_skipped} (already scanned)")
        print(f"  Files with errors:   {files_errored}")

        if error_log:
            print()
            print("  Errors:")
            for name, msg in error_log:
                print(f"    - {name}: {msg}")

        # Print database stats
        stats = db.get_stats()
        print()
        print("=" * 60)
        print("  Catalog Stats")
        print("=" * 60)
        print(f"  Total samples:       {stats['total_count']}")
        if stats["avg_bpm"]:
            print(f"  Average BPM:         {stats['avg_bpm']}")
        total_dur = stats["total_duration_seconds"]
        if total_dur:
            hours = total_dur / 3600
            print(f"  Total duration:      {hours:.1f} hours ({total_dur:.0f}s)")
        size_mb = stats["total_size_bytes"] / (1024 * 1024)
        if size_mb:
            print(f"  Total size:          {size_mb:.1f} MB")
        if stats["by_format"]:
            print(f"  By format:           {stats['by_format']}")
        if stats["by_category"]:
            print(f"  By category:         {stats['by_category']}")
        print(f"  Database path:       {db_path}")
        print()

        return {
            "files_scanned": files_scanned,
            "files_skipped": files_skipped,
            "files_errored": files_errored,
        }

    finally:
        db.close()


def main() -> None:
    """CLI entry point for the sample library scanner."""
    parser = argparse.ArgumentParser(
        description="Scan audio samples and catalog metadata in SQLite.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/scan_samples.py\n"
            "  python scripts/scan_samples.py --samples-dir ~/Music/Samples\n"
            "  python scripts/scan_samples.py --force-rescan --verbose\n"
        ),
    )
    parser.add_argument(
        "--samples-dir",
        type=str,
        default=str(Path.home() / "Music" / "Samples"),
        help="Path to the samples root directory (default: ~/Music/Samples).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to the SQLite database file (default: data/samples.db).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging output.",
    )
    parser.add_argument(
        "--force-rescan",
        action="store_true",
        help="Re-analyze files even if already in the database.",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    samples_dir = Path(args.samples_dir).resolve()
    if not samples_dir.is_dir():
        print(f"Error: Samples directory not found: {samples_dir}", file=sys.stderr)
        print("Create it with: mkdir -p ~/Music/Samples", file=sys.stderr)
        sys.exit(1)

    if args.db_path:
        db_path = Path(args.db_path).resolve()
    else:
        db_path = Path(__file__).resolve().parent.parent / "data" / "samples.db"

    print("=" * 60)
    print("  Sample Library Scanner")
    print("=" * 60)
    print(f"  Samples dir: {samples_dir}")
    print(f"  Database:    {db_path}")
    print()

    result = run_scan(samples_dir, db_path, args.force_rescan, args.verbose)

    if result["files_errored"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
