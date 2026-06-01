"""Downtime analysis module for Stresscon maintenance logs.

Aggregates downtime data by issue category, monthly trends, and
identifies top offending machines.
"""

from typing import Union

import pandas as pd


def load_logs(source: Union[str, pd.DataFrame]) -> pd.DataFrame:
    """Load maintenance logs from a CSV path or existing DataFrame.

    Parses DowntimeStart and DowntimeEnd as datetime columns.
    """
    if isinstance(source, pd.DataFrame):
        df = source.copy()
    else:
        df = pd.read_csv(source)

    for col in ("DowntimeStart", "DowntimeEnd"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col])
    return df


def calculate_downtime_minutes(df: pd.DataFrame) -> pd.DataFrame:
    """Add a DowntimeMinutes column computed from DowntimeEnd - DowntimeStart."""
    df = df.copy()
    if "DowntimeStart" in df.columns and "DowntimeEnd" in df.columns:
        delta = df["DowntimeEnd"] - df["DowntimeStart"]
        df["DowntimeMinutes"] = delta.dt.total_seconds() / 60.0
    return df


def aggregate_by_category(df: pd.DataFrame) -> pd.DataFrame:
    """Group by IssueCategory and sum DowntimeMinutes.

    Returns a DataFrame with columns: IssueCategory, TotalDowntimeMinutes, Count.
    """
    if "DowntimeMinutes" not in df.columns:
        df = calculate_downtime_minutes(df)
    grouped = (
        df.groupby("IssueCategory")
        .agg(TotalDowntimeMinutes=("DowntimeMinutes", "sum"), Count=("DowntimeMinutes", "count"))
        .reset_index()
        .sort_values("TotalDowntimeMinutes", ascending=False)
    )
    return grouped


def monthly_trends(df: pd.DataFrame) -> pd.DataFrame:
    """Group by month and IssueCategory, summing DowntimeMinutes.

    Returns a pivot table with months as rows and categories as columns.
    """
    if "DowntimeMinutes" not in df.columns:
        df = calculate_downtime_minutes(df)
    df = df.copy()
    df["Month"] = df["DowntimeStart"].dt.to_period("M")
    pivot = df.pivot_table(
        index="Month",
        columns="IssueCategory",
        values="DowntimeMinutes",
        aggfunc="sum",
        fill_value=0,
    )
    return pivot


def top_offenders(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    """Return the top N machines by total downtime minutes.

    Returns a DataFrame with columns: AssetID, Title, TotalDowntimeMinutes.
    """
    if "DowntimeMinutes" not in df.columns:
        df = calculate_downtime_minutes(df)

    id_col = "AssetID" if "AssetID" in df.columns else "Title"
    agg_cols = {"TotalDowntimeMinutes": ("DowntimeMinutes", "sum")}
    if "Title" in df.columns and id_col == "AssetID":
        # Include equipment name with the first occurrence
        grouped = df.groupby(id_col).agg(
            TotalDowntimeMinutes=("DowntimeMinutes", "sum"),
            Title=("Title", "first"),
        )
    else:
        grouped = df.groupby(id_col).agg(**agg_cols)

    return (
        grouped.reset_index()
        .sort_values("TotalDowntimeMinutes", ascending=False)
        .head(n)
    )
