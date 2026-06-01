"""Cost of Idleness calculator for Stresscon maintenance analytics.

Computes financial impact of machine downtime based on labor rates
and missed production output.
"""

import pandas as pd

from stresscon.config import DEFAULT_LABOR_RATE, DEFAULT_PRODUCTION_RATE


def cost_of_idleness(
    downtime_minutes: float,
    hourly_labor_rate: float = DEFAULT_LABOR_RATE,
    production_rate_per_hour: float = DEFAULT_PRODUCTION_RATE,
) -> dict[str, float]:
    """Compute the financial cost of a given downtime period.

    Args:
        downtime_minutes: Total minutes of machine downtime.
        hourly_labor_rate: Cost per hour of idle labor ($/hr).
        production_rate_per_hour: Units of output lost per hour of downtime.

    Returns:
        Dictionary with labor_cost, lost_production_units, and total_cost.
    """
    hours = downtime_minutes / 60.0
    labor_cost = hours * hourly_labor_rate
    lost_units = hours * production_rate_per_hour
    return {
        "downtime_minutes": downtime_minutes,
        "downtime_hours": hours,
        "labor_cost": round(labor_cost, 2),
        "lost_production_units": round(lost_units, 2),
        "total_cost": round(labor_cost, 2),
    }


def department_cost_report(
    df: pd.DataFrame,
    labor_rate: float = DEFAULT_LABOR_RATE,
    production_rate: float = DEFAULT_PRODUCTION_RATE,
) -> pd.DataFrame:
    """Aggregate cost of idleness by IssueCategory.

    Expects the DataFrame to already have a DowntimeMinutes column.

    Returns a DataFrame with columns:
        IssueCategory, TotalDowntimeMinutes, LaborCost, LostUnits
    """
    if "DowntimeMinutes" not in df.columns:
        raise ValueError("DataFrame must contain a DowntimeMinutes column.")

    grouped = (
        df.groupby("IssueCategory")
        .agg(TotalDowntimeMinutes=("DowntimeMinutes", "sum"))
        .reset_index()
    )
    grouped["DowntimeHours"] = grouped["TotalDowntimeMinutes"] / 60.0
    grouped["LaborCost"] = (grouped["DowntimeHours"] * labor_rate).round(2)
    grouped["LostUnits"] = (grouped["DowntimeHours"] * production_rate).round(2)
    return grouped.sort_values("LaborCost", ascending=False)
