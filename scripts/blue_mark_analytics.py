"""CLI script for Blue Mark Report trend analysis.

Runs analytics on the Blue Mark Report SQLite database containing 3+ years
of precast concrete piece QA tracking data.  Produces console-formatted
summary tables and an optional Excel workbook with one sheet per analysis
section.

Usage:
    python scripts/blue_mark_analytics.py
    python scripts/blue_mark_analytics.py --db-path data/blue_mark.db --year 2024
    python scripts/blue_mark_analytics.py --output report.xlsx --job 12345
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Add parent to path so stresscon package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stresscon.blue_mark_db import BlueMarkDB

logger = logging.getLogger(__name__)

# Piece type display labels
PIECE_TYPE_LABELS: dict[str, str] = {
    "W": "Wall",
    "DT": "Double Tee",
    "AIW": "Architectural Insulated Wall",
    "IW": "Insulated Wall",
    "FS": "Flat Slab",
    "RB": "RB",
    "ITB": "ITB",
}

# Legacy QA stage columns (boolean flags, not sequential)
LEGACY_QA_STAGES: list[tuple[str, str]] = [
    ("blue_marked", "Blue Marked"),
    ("patching_cleaning", "Patching / Cleaning"),
    ("weld_on_required", "Weld-On Required"),
    ("ncr_response", "NCR Response"),
    ("ncr_repair", "NCR Repair"),
]


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------

def print_section(title: str) -> None:
    """Print a section header matching the run_analysis.py style."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def print_table(headers: list[str], rows: list[list[str]], col_widths: Optional[list[int]] = None) -> None:
    """Print an aligned console table without external libraries.

    Parameters
    ----------
    headers:
        Column header labels.
    rows:
        List of rows, each row a list of string-formatted values.
    col_widths:
        Explicit column widths.  When *None*, widths are auto-calculated
        from the longest value in each column (including the header).
    """
    if col_widths is None:
        col_widths = []
        for i, h in enumerate(headers):
            max_w = len(h)
            for row in rows:
                if i < len(row):
                    max_w = max(max_w, len(row[i]))
            col_widths.append(max_w + 2)

    fmt = "".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("-" * sum(col_widths))
    for row in rows:
        print(fmt.format(*row))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(db: BlueMarkDB, job: Optional[int] = None, year: Optional[int] = None) -> pd.DataFrame:
    """Load pieces table into a DataFrame, applying optional filters.

    Parameters
    ----------
    db:
        An already-connected :class:`BlueMarkDB` instance.
    job:
        If provided, restrict to this job number.
    year:
        If provided, restrict to records whose ``report_date`` falls in
        this calendar year.

    Returns
    -------
    pd.DataFrame
        Full pieces table (or filtered subset) with ``report_date``
        parsed as datetime.
    """
    query = "SELECT * FROM pieces WHERE 1=1"
    params: list = []

    if job is not None:
        query += " AND job_number = ?"
        params.append(job)
    if year is not None:
        query += " AND report_date >= ? AND report_date < ?"
        params.append(f"{year}-01-01")
        params.append(f"{year + 1}-01-01")

    df = pd.read_sql(query, db.conn, params=params)
    df["report_date"] = pd.to_datetime(df["report_date"])
    return df


# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------

def volume_summary(df: pd.DataFrame) -> dict:
    """Compute high-level volume statistics.

    Returns a dict with total_records, unique_pieces, unique_jobs,
    date_range, and by_schema breakdown.
    """
    stats: dict = {
        "total_records": len(df),
        "unique_pieces": df["piece_number"].nunique(),
        "unique_jobs": df["job_number"].nunique(),
        "date_min": df["report_date"].min(),
        "date_max": df["report_date"].max(),
        "by_schema": df.groupby("schema_version").size().to_dict(),
    }
    return stats


def monthly_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Pieces per calendar month.

    Returns a DataFrame with columns: year_month, piece_count.
    """
    df = df.copy()
    df["year_month"] = df["report_date"].dt.to_period("M")
    monthly = (
        df.groupby("year_month")
        .size()
        .reset_index(name="piece_count")
        .sort_values("year_month")
    )
    monthly["year_month"] = monthly["year_month"].astype(str)
    return monthly


def piece_type_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """Count and percentage by piece_type.

    Returns a DataFrame with columns: piece_type, label, count, pct.
    """
    counts = df["piece_type"].value_counts().reset_index()
    counts.columns = ["piece_type", "count"]
    total = counts["count"].sum()
    counts["pct"] = (counts["count"] / total * 100).round(1)
    counts["label"] = counts["piece_type"].map(PIECE_TYPE_LABELS).fillna("Unknown")
    counts = counts[["piece_type", "label", "count", "pct"]].sort_values("count", ascending=False)
    return counts.reset_index(drop=True)


def job_analysis(df: pd.DataFrame, top_n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Top jobs by piece count and by NCR issues.

    Returns
    -------
    top_by_count : pd.DataFrame
        Top *top_n* jobs by total piece count.
    top_by_ncr : pd.DataFrame
        Top *top_n* jobs by NCR response + NCR repair count.
    """
    by_count = (
        df.groupby("job_number")
        .size()
        .reset_index(name="piece_count")
        .sort_values("piece_count", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )

    ncr_df = df.copy()
    ncr_df["ncr_issues"] = ncr_df["ncr_response"].fillna(0) + ncr_df["ncr_repair"].fillna(0)
    by_ncr = (
        ncr_df.groupby("job_number")
        .agg(ncr_issues=("ncr_issues", "sum"), piece_count=("piece_number", "count"))
        .reset_index()
        .sort_values("ncr_issues", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )
    by_ncr["ncr_rate_pct"] = (by_ncr["ncr_issues"] / by_ncr["piece_count"] * 100).round(1)

    return by_count, by_ncr


def qa_stage_analysis(df: pd.DataFrame) -> pd.DataFrame:
    """Percentage of legacy pieces with each QA stage flag set.

    Each stage is independent -- a piece can have any combination of
    marks.  Returns a DataFrame with columns: stage, label, count, pct.
    """
    legacy = df[df["schema_version"] == "legacy"]
    total = len(legacy)
    if total == 0:
        return pd.DataFrame(columns=["stage", "label", "count", "pct"])

    rows = []
    for col, label in LEGACY_QA_STAGES:
        count = int(legacy[col].fillna(0).astype(bool).sum())
        pct = round(count / total * 100, 1)
        rows.append({"stage": col, "label": label, "count": count, "pct": pct})

    return pd.DataFrame(rows)


def ncr_monthly_trend(df: pd.DataFrame) -> pd.DataFrame:
    """NCR rate by calendar month.

    Returns a DataFrame with columns: year_month, total_pieces,
    ncr_pieces, ncr_rate_pct.
    """
    df = df.copy()
    df["year_month"] = df["report_date"].dt.to_period("M")
    df["has_ncr"] = (df["ncr_response"].fillna(0) + df["ncr_repair"].fillna(0)) > 0

    monthly = (
        df.groupby("year_month")
        .agg(total_pieces=("piece_number", "count"), ncr_pieces=("has_ncr", "sum"))
        .reset_index()
        .sort_values("year_month")
    )
    monthly["ncr_rate_pct"] = (monthly["ncr_pieces"] / monthly["total_pieces"] * 100).round(1)
    monthly["year_month"] = monthly["year_month"].astype(str)
    return monthly


def ncr_by_piece_type(df: pd.DataFrame) -> pd.DataFrame:
    """NCR frequency broken out by piece type.

    Returns a DataFrame with columns: piece_type, total_pieces,
    ncr_pieces, ncr_rate_pct.
    """
    df = df.copy()
    df["has_ncr"] = (df["ncr_response"].fillna(0) + df["ncr_repair"].fillna(0)) > 0

    result = (
        df.groupby("piece_type")
        .agg(total_pieces=("piece_number", "count"), ncr_pieces=("has_ncr", "sum"))
        .reset_index()
        .sort_values("ncr_pieces", ascending=False)
    )
    result["ncr_rate_pct"] = (result["ncr_pieces"] / result["total_pieces"] * 100).round(1)
    return result.reset_index(drop=True)


def ncr_by_job(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """NCR frequency broken out by job number.

    Returns the top *top_n* jobs with the most NCR-flagged pieces.
    """
    df = df.copy()
    df["has_ncr"] = (df["ncr_response"].fillna(0) + df["ncr_repair"].fillna(0)) > 0

    result = (
        df.groupby("job_number")
        .agg(total_pieces=("piece_number", "count"), ncr_pieces=("has_ncr", "sum"))
        .reset_index()
        .sort_values("ncr_pieces", ascending=False)
        .head(top_n)
    )
    result["ncr_rate_pct"] = (result["ncr_pieces"] / result["total_pieces"] * 100).round(1)
    return result.reset_index(drop=True)


def throughput_analysis(df: pd.DataFrame) -> dict:
    """Compute throughput statistics.

    Returns a dict with avg_pieces_per_day, busiest_days (top 5),
    and busiest_months (top 5).
    """
    daily = (
        df.groupby(df["report_date"].dt.date)
        .size()
        .reset_index(name="piece_count")
    )
    daily.columns = ["date", "piece_count"]

    avg_per_day = daily["piece_count"].mean() if len(daily) > 0 else 0.0

    busiest_days = daily.sort_values("piece_count", ascending=False).head(5).reset_index(drop=True)
    busiest_days["date"] = busiest_days["date"].astype(str)

    df_copy = df.copy()
    df_copy["year_month"] = df_copy["report_date"].dt.to_period("M")
    monthly = (
        df_copy.groupby("year_month")
        .size()
        .reset_index(name="piece_count")
        .sort_values("piece_count", ascending=False)
        .head(5)
        .reset_index(drop=True)
    )
    monthly["year_month"] = monthly["year_month"].astype(str)

    return {
        "avg_pieces_per_day": round(avg_per_day, 1),
        "busiest_days": busiest_days,
        "busiest_months": monthly,
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

def print_volume_summary(stats: dict) -> None:
    """Render volume summary to console."""
    print_section("Volume Summary")
    print(f"  Total records:        {stats['total_records']:,}")
    print(f"  Unique piece numbers: {stats['unique_pieces']:,}")
    print(f"  Unique jobs:          {stats['unique_jobs']:,}")
    if pd.notna(stats["date_min"]) and pd.notna(stats["date_max"]):
        d_min = pd.Timestamp(stats["date_min"]).strftime("%Y-%m-%d")
        d_max = pd.Timestamp(stats["date_max"]).strftime("%Y-%m-%d")
        print(f"  Date range:           {d_min}  to  {d_max}")
    print()
    print("  Records by schema version:")
    for schema, count in stats["by_schema"].items():
        print(f"    {schema:<12} {count:>8,}")


def print_monthly_volume(monthly: pd.DataFrame) -> None:
    """Render monthly volume table to console."""
    print_section("Monthly Volume Trends")
    headers = ["Month", "Pieces"]
    rows = [[row["year_month"], f"{row['piece_count']:,}"] for _, row in monthly.iterrows()]
    print_table(headers, rows)


def print_piece_type_dist(dist: pd.DataFrame) -> None:
    """Render piece type distribution to console."""
    print_section("Piece Type Distribution")
    headers = ["Type", "Label", "Count", "Pct (%)"]
    rows = [
        [row["piece_type"], row["label"], f"{row['count']:,}", f"{row['pct']:.1f}"]
        for _, row in dist.iterrows()
    ]
    print_table(headers, rows)


def print_job_analysis(top_by_count: pd.DataFrame, top_by_ncr: pd.DataFrame) -> None:
    """Render job analysis tables to console."""
    print_section("Top 10 Jobs by Piece Count")
    headers = ["Job #", "Pieces"]
    rows = [[str(row["job_number"]), f"{row['piece_count']:,}"] for _, row in top_by_count.iterrows()]
    print_table(headers, rows)

    print_section("Top 10 Jobs by NCR Issues")
    headers = ["Job #", "NCR Issues", "Pieces", "NCR Rate (%)"]
    rows = [
        [
            str(row["job_number"]),
            f"{int(row['ncr_issues']):,}",
            f"{row['piece_count']:,}",
            f"{row['ncr_rate_pct']:.1f}",
        ]
        for _, row in top_by_ncr.iterrows()
    ]
    print_table(headers, rows)


def print_qa_stages(qa_df: pd.DataFrame) -> None:
    """Render QA stage analysis to console."""
    print_section("QA Stage Analysis (Legacy Data)")
    if qa_df.empty:
        print("  No legacy schema records found.")
        return
    headers = ["Stage", "Count", "Pct (%)"]
    rows = [
        [row["label"], f"{row['count']:,}", f"{row['pct']:.1f}"]
        for _, row in qa_df.iterrows()
    ]
    print_table(headers, rows)


def print_ncr_analysis(
    trend: pd.DataFrame,
    by_type: pd.DataFrame,
    by_job: pd.DataFrame,
) -> None:
    """Render NCR analysis sections to console."""
    print_section("NCR Rate Over Time (Monthly)")
    headers = ["Month", "Total", "NCR", "Rate (%)"]
    rows = [
        [
            row["year_month"],
            f"{row['total_pieces']:,}",
            f"{int(row['ncr_pieces']):,}",
            f"{row['ncr_rate_pct']:.1f}",
        ]
        for _, row in trend.iterrows()
    ]
    print_table(headers, rows)

    print_section("NCR Frequency by Piece Type")
    headers = ["Type", "Total", "NCR", "Rate (%)"]
    rows = [
        [
            str(row["piece_type"]),
            f"{row['total_pieces']:,}",
            f"{int(row['ncr_pieces']):,}",
            f"{row['ncr_rate_pct']:.1f}",
        ]
        for _, row in by_type.iterrows()
    ]
    print_table(headers, rows)

    print_section("NCR Frequency by Job (Top 10)")
    headers = ["Job #", "Total", "NCR", "Rate (%)"]
    rows = [
        [
            str(row["job_number"]),
            f"{row['total_pieces']:,}",
            f"{int(row['ncr_pieces']):,}",
            f"{row['ncr_rate_pct']:.1f}",
        ]
        for _, row in by_job.iterrows()
    ]
    print_table(headers, rows)


def print_throughput(tp: dict) -> None:
    """Render throughput analysis to console."""
    print_section("Throughput Analysis")
    print(f"  Average pieces per report day: {tp['avg_pieces_per_day']:.1f}")

    print("\n  Busiest Days:")
    headers = ["Date", "Pieces"]
    rows = [[row["date"], f"{row['piece_count']:,}"] for _, row in tp["busiest_days"].iterrows()]
    print_table(headers, rows)

    print("\n  Busiest Months:")
    headers = ["Month", "Pieces"]
    rows = [[row["year_month"], f"{row['piece_count']:,}"] for _, row in tp["busiest_months"].iterrows()]
    print_table(headers, rows)


# ---------------------------------------------------------------------------
# Excel export
# ---------------------------------------------------------------------------

def export_to_excel(
    output_path: Path,
    vol_stats: dict,
    monthly: pd.DataFrame,
    type_dist: pd.DataFrame,
    top_by_count: pd.DataFrame,
    top_by_ncr: pd.DataFrame,
    qa_df: pd.DataFrame,
    ncr_trend: pd.DataFrame,
    ncr_type: pd.DataFrame,
    ncr_job: pd.DataFrame,
    tp: dict,
) -> None:
    """Write all analysis DataFrames to an Excel workbook.

    Each analysis section gets its own worksheet.  Uses openpyxl via
    pandas ExcelWriter.
    """
    logger.info("Writing Excel report to %s", output_path)

    # Build a small summary DataFrame from the volume stats dict
    summary_rows = [
        {"Metric": "Total Records", "Value": vol_stats["total_records"]},
        {"Metric": "Unique Pieces", "Value": vol_stats["unique_pieces"]},
        {"Metric": "Unique Jobs", "Value": vol_stats["unique_jobs"]},
    ]
    if pd.notna(vol_stats["date_min"]) and pd.notna(vol_stats["date_max"]):
        d_min = pd.Timestamp(vol_stats["date_min"]).strftime("%Y-%m-%d")
        d_max = pd.Timestamp(vol_stats["date_max"]).strftime("%Y-%m-%d")
        summary_rows.append({"Metric": "Date Range Start", "Value": d_min})
        summary_rows.append({"Metric": "Date Range End", "Value": d_max})
    for schema, count in vol_stats["by_schema"].items():
        summary_rows.append({"Metric": f"Schema: {schema}", "Value": count})
    summary_df = pd.DataFrame(summary_rows)

    with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Volume Summary", index=False)
        monthly.to_excel(writer, sheet_name="Monthly Volume", index=False)
        type_dist.to_excel(writer, sheet_name="Piece Type Dist", index=False)
        top_by_count.to_excel(writer, sheet_name="Top Jobs by Count", index=False)
        top_by_ncr.to_excel(writer, sheet_name="Top Jobs by NCR", index=False)
        if not qa_df.empty:
            qa_df.to_excel(writer, sheet_name="QA Stages", index=False)
        ncr_trend.to_excel(writer, sheet_name="NCR Monthly Trend", index=False)
        ncr_type.to_excel(writer, sheet_name="NCR by Piece Type", index=False)
        ncr_job.to_excel(writer, sheet_name="NCR by Job", index=False)
        tp["busiest_days"].to_excel(writer, sheet_name="Busiest Days", index=False)
        tp["busiest_months"].to_excel(writer, sheet_name="Busiest Months", index=False)

    logger.info("Excel report saved: %s", output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments, run all analyses, print results."""
    parser = argparse.ArgumentParser(
        description="Blue Mark Report trend analysis for precast concrete QA tracking",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default="data/blue_mark.db",
        help="Path to the Blue Mark SQLite database (default: data/blue_mark.db)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional Excel (.xlsx) file path to save detailed report",
    )
    parser.add_argument(
        "--job",
        type=int,
        default=None,
        help="Filter analysis to a specific job number",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Filter analysis to a specific calendar year",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    db_path = Path(args.db_path)
    if not db_path.exists():
        logger.error("Database not found: %s", db_path)
        sys.exit(1)

    # Connect and load data
    db = BlueMarkDB(db_path=db_path)
    db.connect()

    try:
        # Describe active filters
        filters: list[str] = []
        if args.job is not None:
            filters.append(f"job={args.job}")
        if args.year is not None:
            filters.append(f"year={args.year}")
        filter_label = f"  (filters: {', '.join(filters)})" if filters else ""

        print(f"\nBlue Mark Analytics — {db_path}{filter_label}")

        df = load_data(db, job=args.job, year=args.year)
        if df.empty:
            print("\n  No records match the specified filters.")
            sys.exit(0)

        # 1. Volume Summary
        vol_stats = volume_summary(df)
        print_volume_summary(vol_stats)

        # 2. Monthly Volume Trends
        monthly = monthly_volume(df)
        print_monthly_volume(monthly)

        # 3. Piece Type Distribution
        type_dist = piece_type_distribution(df)
        print_piece_type_dist(type_dist)

        # 4. Job Analysis
        top_by_count, top_by_ncr = job_analysis(df)
        print_job_analysis(top_by_count, top_by_ncr)

        # 5. QA Stage Analysis (legacy)
        qa_df = qa_stage_analysis(df)
        print_qa_stages(qa_df)

        # 6. NCR Analysis
        ncr_trend = ncr_monthly_trend(df)
        ncr_type = ncr_by_piece_type(df)
        ncr_job_df = ncr_by_job(df)
        print_ncr_analysis(ncr_trend, ncr_type, ncr_job_df)

        # 7. Throughput
        tp = throughput_analysis(df)
        print_throughput(tp)

        # Optional Excel export
        if args.output:
            output_path = Path(args.output)
            export_to_excel(
                output_path,
                vol_stats,
                monthly,
                type_dist,
                top_by_count,
                top_by_ncr,
                qa_df,
                ncr_trend,
                ncr_type,
                ncr_job_df,
                tp,
            )
            print(f"\n  Excel report saved to: {output_path}")

    finally:
        db.close()

    print()


if __name__ == "__main__":
    main()
