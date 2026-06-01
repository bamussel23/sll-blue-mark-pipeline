"""Tests for the downtime analyzer module."""

import pandas as pd
import pytest

from stresscon.downtime_analyzer import (
    aggregate_by_category,
    calculate_downtime_minutes,
    load_logs,
    monthly_trends,
    top_offenders,
)


@pytest.fixture
def sample_df() -> pd.DataFrame:
    """Create a small fixture DataFrame for testing."""
    return pd.DataFrame(
        {
            "AssetID": ["CRN-01", "CRN-01", "MIX-01", "MIX-01", "FORM-01"],
            "Title": [
                "Overhead Crane #1",
                "Overhead Crane #1",
                "Batch Mixer Primary",
                "Batch Mixer Primary",
                "Double Tee Form A",
            ],
            "IssueCategory": [
                "Mechanical",
                "Electrical",
                "Mechanical",
                "Hydraulic",
                "Mechanical",
            ],
            "SeverityLevel": [
                "Critical (Line Down)",
                "High (Needs Repair)",
                "Routine (Scheduled)",
                "Critical (Line Down)",
                "High (Needs Repair)",
            ],
            "DowntimeStart": pd.to_datetime(
                [
                    "2025-06-01 08:00",
                    "2025-06-15 14:00",
                    "2025-07-01 06:00",
                    "2025-07-10 09:00",
                    "2025-07-20 10:00",
                ]
            ),
            "DowntimeEnd": pd.to_datetime(
                [
                    "2025-06-01 12:00",  # 240 min
                    "2025-06-15 15:30",  # 90 min
                    "2025-07-01 07:00",  # 60 min
                    "2025-07-10 13:00",  # 240 min
                    "2025-07-20 11:30",  # 90 min
                ]
            ),
        }
    )


def test_calculate_downtime_minutes(sample_df: pd.DataFrame) -> None:
    result = calculate_downtime_minutes(sample_df)
    assert "DowntimeMinutes" in result.columns
    assert result["DowntimeMinutes"].iloc[0] == 240.0
    assert result["DowntimeMinutes"].iloc[1] == 90.0
    assert result["DowntimeMinutes"].iloc[2] == 60.0


def test_aggregate_by_category(sample_df: pd.DataFrame) -> None:
    df = calculate_downtime_minutes(sample_df)
    result = aggregate_by_category(df)
    assert "IssueCategory" in result.columns
    assert "TotalDowntimeMinutes" in result.columns
    assert "Count" in result.columns
    # Mechanical: 240 + 60 + 90 = 390
    mech = result[result["IssueCategory"] == "Mechanical"]
    assert mech["TotalDowntimeMinutes"].values[0] == 390.0
    assert mech["Count"].values[0] == 3


def test_monthly_trends(sample_df: pd.DataFrame) -> None:
    df = calculate_downtime_minutes(sample_df)
    result = monthly_trends(df)
    # Should have 2 months (June and July)
    assert len(result) == 2
    assert "Mechanical" in result.columns


def test_top_offenders(sample_df: pd.DataFrame) -> None:
    df = calculate_downtime_minutes(sample_df)
    result = top_offenders(df, n=3)
    # CRN-01 has 330 min, MIX-01 has 300 min, FORM-01 has 90 min
    assert result.iloc[0]["AssetID"] == "CRN-01"
    assert result.iloc[0]["TotalDowntimeMinutes"] == 330.0
    assert len(result) == 3


def test_load_logs_from_dataframe(sample_df: pd.DataFrame) -> None:
    result = load_logs(sample_df)
    assert len(result) == 5
    assert pd.api.types.is_datetime64_any_dtype(result["DowntimeStart"])
