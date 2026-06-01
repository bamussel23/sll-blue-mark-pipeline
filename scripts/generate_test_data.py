"""Generate realistic sample maintenance log data for testing.

Creates 200 rows of fake maintenance records with realistic asset IDs,
issue categories, severities, and date ranges spanning the last 12 months.
Outputs to data/test/sample_maintenance_logs.csv.
"""

import csv
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

ASSET_IDS = {
    "CRN-01": "Overhead Crane #1",
    "CRN-02": "Overhead Crane #2",
    "CRN-03": "Gantry Crane",
    "CRN-04": "Jib Crane East",
    "CRN-05": "Jib Crane West",
    "MIX-01": "Batch Mixer Primary",
    "MIX-02": "Batch Mixer Secondary",
    "MIX-03": "Color Mixer",
    "FORM-01": "Double Tee Form A",
    "FORM-02": "Double Tee Form B",
    "FORM-03": "Wall Form #1",
    "FORM-04": "Beam Form #1",
    "BATCH-01": "Batch Plant Main",
    "BATCH-02": "Batch Plant Auxiliary",
}

ISSUE_CATEGORIES = [
    "Mechanical",
    "Electrical",
    "Hydraulic",
    "Pneumatic",
    "Software",
    "Safety",
]

SEVERITIES = [
    "Critical (Line Down)",
    "High (Needs Repair)",
    "Routine (Scheduled)",
]

STATUSES = ["New", "In Progress", "Waiting for Parts", "Resolved"]

TECHNICIANS = [
    "Martinez, J.",
    "Thompson, R.",
    "Williams, K.",
    "Garcia, M.",
    "Anderson, T.",
]

DESCRIPTIONS = [
    "Bearing noise detected during operation",
    "Hydraulic fluid leak at cylinder seal",
    "Electrical fault on motor contactor",
    "Scheduled preventative maintenance",
    "Safety switch malfunction",
    "PLC communication error",
    "Pneumatic valve not actuating",
    "Belt tension requires adjustment",
    "Overheating warning on VFD",
    "Worn brake pads require replacement",
    "Cable fraying near sheave",
    "Concrete buildup on form surface",
    "Vibration analysis indicates imbalance",
    "Emergency stop circuit test",
    "Lubrication schedule due",
]

PARTS = [
    "BRG-6205-2RS",
    "SEAL-HYD-50MM",
    "CONT-3P-30A",
    "BELT-V-B68",
    "VALVE-SOL-24V",
    "FILTER-HYD-10UM",
    "PAD-BRAKE-8IN",
    "GREASE-NLGI2-TUBE",
    "FUSE-30A-600V",
    "",
]


def generate_row(row_num: int, base_date: datetime) -> dict:
    asset_id = random.choice(list(ASSET_IDS.keys()))
    equipment_name = ASSET_IDS[asset_id]
    category = random.choice(ISSUE_CATEGORIES)
    severity = random.choice(SEVERITIES)
    status = random.choice(STATUSES)
    technician = random.choice(TECHNICIANS)
    description = random.choice(DESCRIPTIONS)

    # Random start time within the last 12 months
    days_ago = random.randint(0, 365)
    hour = random.randint(5, 22)
    minute = random.randint(0, 59)
    start = base_date - timedelta(days=days_ago, hours=random.randint(0, 12))
    start = start.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # Downtime between 15 minutes and 48 hours depending on severity
    if "Critical" in severity:
        downtime_min = random.randint(60, 2880)
    elif "High" in severity:
        downtime_min = random.randint(30, 480)
    else:
        downtime_min = random.randint(15, 120)

    end = start + timedelta(minutes=downtime_min)

    # Parts used (0-3 parts)
    num_parts = random.randint(0, 3)
    parts_used = "; ".join(random.sample([p for p in PARTS if p], min(num_parts, len(PARTS) - 1)))

    # Estimated cost
    cost = round(random.uniform(25.0, 5000.0), 2) if parts_used else round(random.uniform(25.0, 200.0), 2)

    return {
        "AssetID": asset_id,
        "Title": equipment_name,
        "IssueCategory": category,
        "SeverityLevel": severity,
        "WorkStatus": status,
        "Technician": technician,
        "Description": description,
        "DowntimeStart": start.isoformat(),
        "DowntimeEnd": end.isoformat(),
        "PartsUsed": parts_used,
        "EstimatedCost": cost,
    }


def main() -> None:
    random.seed(42)
    base_date = datetime.now()
    rows = [generate_row(i, base_date) for i in range(200)]

    output_dir = Path(__file__).resolve().parent.parent.parent / "data" / "test"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "sample_maintenance_logs.csv"

    fieldnames = [
        "AssetID",
        "Title",
        "IssueCategory",
        "SeverityLevel",
        "WorkStatus",
        "Technician",
        "Description",
        "DowntimeStart",
        "DowntimeEnd",
        "PartsUsed",
        "EstimatedCost",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Generated {len(rows)} maintenance log records -> {output_path}")


if __name__ == "__main__":
    main()
