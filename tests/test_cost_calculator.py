"""Tests for the cost calculator module."""

import pandas as pd
import pytest

from stresscon.cost_calculator import cost_of_idleness, department_cost_report


def test_cost_of_idleness_basic() -> None:
    result = cost_of_idleness(
        downtime_minutes=120.0,
        hourly_labor_rate=50.0,
        production_rate_per_hour=2.0,
    )
    assert result["downtime_minutes"] == 120.0
    assert result["downtime_hours"] == 2.0
    assert result["labor_cost"] == 100.0
    assert result["lost_production_units"] == 4.0
    assert result["total_cost"] == 100.0


def test_cost_of_idleness_zero_downtime() -> None:
    result = cost_of_idleness(0.0, 45.0, 1.0)
    assert result["labor_cost"] == 0.0
    assert result["lost_production_units"] == 0.0


def test_cost_of_idleness_fractional() -> None:
    result = cost_of_idleness(30.0, 60.0, 10.0)
    # 30 min = 0.5 hr, labor = 30.0, units = 5.0
    assert result["downtime_hours"] == 0.5
    assert result["labor_cost"] == 30.0
    assert result["lost_production_units"] == 5.0


def test_department_cost_report() -> None:
    df = pd.DataFrame(
        {
            "IssueCategory": ["Mechanical", "Mechanical", "Electrical"],
            "DowntimeMinutes": [120.0, 60.0, 240.0],
        }
    )
    result = department_cost_report(df, labor_rate=60.0, production_rate=1.0)
    assert len(result) == 2
    # Electrical: 240 min = 4 hrs * $60 = $240
    elec = result[result["IssueCategory"] == "Electrical"]
    assert elec["LaborCost"].values[0] == 240.0
    # Mechanical: 180 min = 3 hrs * $60 = $180
    mech = result[result["IssueCategory"] == "Mechanical"]
    assert mech["LaborCost"].values[0] == 180.0


def test_department_cost_report_missing_column() -> None:
    df = pd.DataFrame({"IssueCategory": ["Mechanical"]})
    with pytest.raises(ValueError, match="DowntimeMinutes"):
        department_cost_report(df)
