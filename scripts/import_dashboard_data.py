#!/usr/bin/env python3
"""Import VP Operations Dashboard CSV data into SharePoint lists.

This script bulk imports three CSV files into their corresponding SharePoint lists:
- equipment_status.csv -> Equipment Status list
- overtime_analysis.csv -> Overtime Analysis list
- worker_timeline.csv -> Worker Timeline list

Requires SharePoint credentials in .env file:
- SHAREPOINT_URL (defaults to https://enconunited.sharepoint.com/sites/QA)
- SHAREPOINT_CLIENT_ID
- SHAREPOINT_CLIENT_SECRET

Usage:
    python scripts/import_dashboard_data.py --data-dir /path/to/data
"""

import argparse
import logging
from pathlib import Path

from stresscon.bulk_import import import_all_dashboards
from stresscon.sharepoint_client import SharePointClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import VP Operations Dashboard CSV data into SharePoint lists"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("/Users/blakemusselman/vp-dashboard-data"),
        help="Directory containing CSV files (default: /Users/blakemusselman/vp-dashboard-data)",
    )
    parser.add_argument(
        "--site-url",
        type=str,
        default=None,
        help="SharePoint site URL (defaults to env var or QA site)",
    )

    args = parser.parse_args()

    # Verify data directory exists
    if not args.data_dir.exists():
        logger.error(f"Data directory not found: {args.data_dir}")
        return

    try:
        # Connect to SharePoint
        logger.info("Connecting to SharePoint...")
        client = SharePointClient(url=args.site_url)
        client.connect()

        # Import all dashboard data
        logger.info(f"Starting bulk import from {args.data_dir}...")
        results = import_all_dashboards(client, args.data_dir)

        # Print results
        logger.info("\n=== IMPORT RESULTS ===")
        total_imported = 0
        total_errors = 0

        for list_name, stats in results.items():
            rows = stats.get("rows_imported", 0)
            errors = stats.get("errors", [])
            total_imported += rows
            total_errors += len(errors)

            logger.info(f"\n{list_name}:")
            logger.info(f"  Rows imported: {rows}")
            if errors:
                logger.info(f"  Errors ({len(errors)}):")
                for error in errors[:5]:  # Show first 5 errors
                    logger.info(f"    - {error}")
                if len(errors) > 5:
                    logger.info(f"    ... and {len(errors) - 5} more")

        logger.info(f"\n=== SUMMARY ===")
        logger.info(f"Total rows imported: {total_imported}")
        logger.info(f"Total errors: {total_errors}")

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        logger.error(
            "Ensure SHAREPOINT_URL, SHAREPOINT_CLIENT_ID, and "
            "SHAREPOINT_CLIENT_SECRET are set in .env file"
        )
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)


if __name__ == "__main__":
    main()
