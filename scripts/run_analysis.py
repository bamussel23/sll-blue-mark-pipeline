"""CLI entry point for running downtime analysis.

Usage:
    python scripts/run_analysis.py --csv ../data/test/sample_maintenance_logs.csv
    python scripts/run_analysis.py --sharepoint  (requires .env credentials)
"""

import argparse
import sys
from pathlib import Path

# Add parent to path so stresscon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stresscon.downtime_analyzer import (
    aggregate_by_category,
    calculate_downtime_minutes,
    load_logs,
    monthly_trends,
    top_offenders,
)
from stresscon.cost_calculator import cost_of_idleness, department_cost_report
from stresscon.config import DEFAULT_LABOR_RATE, DEFAULT_PRODUCTION_RATE


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stresscon Maintenance Downtime Analysis"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--csv", type=str, help="Path to maintenance logs CSV")
    source.add_argument(
        "--sharepoint",
        action="store_true",
        help="Pull data from SharePoint (requires .env credentials)",
    )
    parser.add_argument(
        "--labor-rate",
        type=float,
        default=DEFAULT_LABOR_RATE,
        help=f"Hourly labor rate (default: ${DEFAULT_LABOR_RATE})",
    )
    parser.add_argument(
        "--production-rate",
        type=float,
        default=DEFAULT_PRODUCTION_RATE,
        help=f"Units per hour production rate (default: {DEFAULT_PRODUCTION_RATE})",
    )
    args = parser.parse_args()

    if args.sharepoint:
        from stresscon.sharepoint_client import SharePointClient

        print("Connecting to SharePoint...")
        client = SharePointClient().connect()
        import pandas as pd

        raw = client.get_maintenance_logs()
        df = pd.DataFrame(raw)
    else:
        df = load_logs(args.csv)

    df = calculate_downtime_minutes(df)

    # Category breakdown
    print_section("Downtime by Issue Category")
    cat_df = aggregate_by_category(df)
    print(cat_df.to_string(index=False))

    # Monthly trends
    print_section("Monthly Downtime Trends (minutes)")
    trends = monthly_trends(df)
    print(trends.to_string())

    # Top offenders
    print_section("Top 5 Machines by Total Downtime")
    top = top_offenders(df, n=5)
    print(top.to_string(index=False))

    # Cost report
    print_section(f"Cost of Idleness (${args.labor_rate}/hr labor)")
    cost_df = department_cost_report(df, args.labor_rate, args.production_rate)
    print(cost_df.to_string(index=False))

    # Summary
    total_minutes = df["DowntimeMinutes"].sum()
    total_cost = cost_of_idleness(total_minutes, args.labor_rate, args.production_rate)
    print_section("Summary")
    print(f"  Total records:           {len(df)}")
    print(f"  Total downtime:          {total_cost['downtime_hours']:.1f} hours")
    print(f"  Estimated labor cost:    ${total_cost['labor_cost']:,.2f}")
    print(f"  Lost production units:   {total_cost['lost_production_units']:,.1f}")


if __name__ == "__main__":
    main()
