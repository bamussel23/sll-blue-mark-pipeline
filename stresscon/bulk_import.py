"""Bulk data import utilities for SharePoint lists.

Provides functions to import CSV data into SharePoint lists using
the Office365 REST Python Client.
"""

import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from stresscon.sharepoint_client import SharePointClient

logger = logging.getLogger(__name__)


def import_csv_to_list(
    client: SharePointClient,
    csv_path: Path,
    list_name: str,
    field_mapping: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Import CSV data into a SharePoint list.

    Args:
        client: Connected SharePointClient instance.
        csv_path: Path to CSV file to import.
        list_name: Title of the target SharePoint list.
        field_mapping: Optional dict mapping CSV columns to SharePoint internal
                       field names. If not provided, uses CSV column names as-is.

    Returns:
        Dictionary with import stats: {'rows_imported': int, 'errors': list}
    """
    df = pd.read_csv(csv_path)
    stats = {"rows_imported": 0, "errors": []}

    sp_list = client.ctx.web.lists.get_by_title(list_name)

    for idx, row in df.iterrows():
        try:
            # Prepare item data
            item_data = {}
            for col in df.columns:
                # Use field mapping if provided, otherwise use column name as-is
                field_name = field_mapping.get(col, col) if field_mapping else col
                value = row[col]

                # Handle NaN/None values
                if pd.isna(value):
                    value = None

                item_data[field_name] = value

            # Add item to list
            sp_list.add_item(item_data)
            stats["rows_imported"] += 1

            if (idx + 1) % 10 == 0:
                logger.info(f"Imported {idx + 1} rows into {list_name}")

        except Exception as e:
            error_msg = f"Row {idx}: {str(e)}"
            logger.error(error_msg)
            stats["errors"].append(error_msg)

    # Execute all queued operations
    client.ctx.execute_query()
    logger.info(
        f"Completed import to {list_name}: {stats['rows_imported']} rows, "
        f"{len(stats['errors'])} errors"
    )

    return stats


def import_equipment_status(
    client: SharePointClient, csv_path: Path
) -> dict[str, Any]:
    """Import equipment_status.csv into Equipment Status list.

    Column mapping:
        EquipmentID -> Title (primary key)
        EquipmentName -> EquipmentName
        Location -> Location
        Status -> Status (choice field)
        LastActive -> LastActive
        CurrentOperator -> CurrentOperator
    """
    field_mapping = {
        "EquipmentID": "Title",
        "EquipmentName": "EquipmentName",
        "Location": "Location",
        "Status": "Status",
        "LastActive": "LastActive",
        "CurrentOperator": "CurrentOperator",
    }

    return import_csv_to_list(
        client,
        csv_path,
        "Equipment Status",
        field_mapping,
    )


def import_overtime_analysis(
    client: SharePointClient, csv_path: Path
) -> dict[str, Any]:
    """Import overtime_analysis.csv into Overtime Analysis list.

    Column mapping:
        Date -> Date
        Worker -> Worker
        ShiftStart -> ShiftStart
        ShiftEnd -> ShiftEnd
        OvertimeHours -> OvertimeHours
        EquipmentUsed -> EquipmentUsed
        ActualProductionHours -> ActualProductionHours
        ProductionUnits -> ProductionUnits
        OvertimeCost -> OvertimeCost
        WastedCost -> WastedCost
    """
    # No field mapping needed for this list (column names match)
    return import_csv_to_list(
        client,
        csv_path,
        "Overtime Analysis",
        field_mapping=None,
    )


def import_worker_timeline(
    client: SharePointClient, csv_path: Path
) -> dict[str, Any]:
    """Import worker_timeline.csv into Worker Timeline list.

    Column mapping:
        WorkerID -> WorkerID
        WorkerName -> WorkerName
        Date -> Date
        ClockIn -> ClockIn
        ClockOut -> ClockOut
        TotalHours -> TotalHours
        RegularHours -> RegularHours
        OvertimeHours -> OvertimeHours
        Equipment -> Equipment
        EquipmentActiveStart -> EquipmentActiveStart
        EquipmentActiveEnd -> EquipmentActiveEnd
        EquipmentActiveHours -> EquipmentActiveHours
        Gap -> Gap
    """
    # No field mapping needed for this list (column names match)
    return import_csv_to_list(
        client,
        csv_path,
        "Worker Timeline",
        field_mapping=None,
    )


def import_all_dashboards(
    client: SharePointClient, data_dir: Path
) -> dict[str, dict[str, Any]]:
    """Bulk import all VP Operations Dashboard CSV files.

    Args:
        client: Connected SharePointClient instance.
        data_dir: Directory containing CSV files.

    Returns:
        Dictionary mapping list names to import statistics.
    """
    results = {}

    # Import equipment status
    try:
        equipment_csv = data_dir / "equipment_status.csv"
        if equipment_csv.exists():
            results["Equipment Status"] = import_equipment_status(client, equipment_csv)
        else:
            logger.warning(f"equipment_status.csv not found at {equipment_csv}")
    except Exception as e:
        logger.error(f"Failed to import equipment status: {e}")
        results["Equipment Status"] = {"rows_imported": 0, "errors": [str(e)]}

    # Import overtime analysis
    try:
        overtime_csv = data_dir / "overtime_analysis.csv"
        if overtime_csv.exists():
            results["Overtime Analysis"] = import_overtime_analysis(
                client, overtime_csv
            )
        else:
            logger.warning(f"overtime_analysis.csv not found at {overtime_csv}")
    except Exception as e:
        logger.error(f"Failed to import overtime analysis: {e}")
        results["Overtime Analysis"] = {"rows_imported": 0, "errors": [str(e)]}

    # Import worker timeline
    try:
        timeline_csv = data_dir / "worker_timeline.csv"
        if timeline_csv.exists():
            results["Worker Timeline"] = import_worker_timeline(client, timeline_csv)
        else:
            logger.warning(f"worker_timeline.csv not found at {timeline_csv}")
    except Exception as e:
        logger.error(f"Failed to import worker timeline: {e}")
        results["Worker Timeline"] = {"rows_imported": 0, "errors": [str(e)]}

    return results
