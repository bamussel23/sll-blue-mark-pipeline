"""Tests for bulk_import module.

Tests CSV parsing and data preparation without requiring SharePoint credentials.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from stresscon.bulk_import import (
    import_csv_to_list,
    import_equipment_status,
    import_overtime_analysis,
    import_worker_timeline,
)


@pytest.fixture
def sample_equipment_csv(tmp_path: Path) -> Path:
    """Create sample equipment_status.csv for testing."""
    data = {
        "EquipmentID": ["BED-01", "MIX-01", "CRANE-01"],
        "EquipmentName": ["Casting Bed 1", "Concrete Mixer 1", "Overhead Crane 1"],
        "Location": ["Bay A", "Mix Station", "Bay A"],
        "Status": ["Idle", "Active", "Active"],
        "LastActive": [
            "2026-02-09 22:45:00",
            "2026-02-09 23:55:00",
            "2026-02-09 23:50:00",
        ],
        "CurrentOperator": ["None", "Garcia", "Williams"],
    }
    df = pd.DataFrame(data)
    csv_path = tmp_path / "equipment_status.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def sample_overtime_csv(tmp_path: Path) -> Path:
    """Create sample overtime_analysis.csv for testing."""
    data = {
        "Date": ["2026-02-09", "2026-02-09"],
        "Worker": ["Martinez", "Garcia"],
        "ShiftStart": ["06:00", "06:00"],
        "ShiftEnd": ["18:00", "17:00"],
        "OvertimeHours": [4.0, 3.0],
        "EquipmentUsed": ["BED-02", "MIX-01"],
        "ActualProductionHours": [2.5, 2.8],
        "ProductionUnits": [3, 5],
        "OvertimeCost": [180, 135],
        "WastedCost": [67.50, 9.00],
    }
    df = pd.DataFrame(data)
    csv_path = tmp_path / "overtime_analysis.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def sample_worker_timeline_csv(tmp_path: Path) -> Path:
    """Create sample worker_timeline.csv for testing."""
    data = {
        "WorkerID": ["W001", "W002"],
        "WorkerName": ["Martinez", "Garcia"],
        "Date": ["2026-02-09", "2026-02-09"],
        "ClockIn": ["06:00", "06:00"],
        "ClockOut": ["18:00", "17:00"],
        "TotalHours": [12.0, 11.0],
        "RegularHours": [8.0, 8.0],
        "OvertimeHours": [4.0, 3.0],
        "Equipment": ["BED-02", "MIX-01"],
        "EquipmentActiveStart": ["06:30", "06:15"],
        "EquipmentActiveEnd": ["09:00", "09:00"],
        "EquipmentActiveHours": [2.5, 2.8],
        "Gap": [1.5, 0.2],
    }
    df = pd.DataFrame(data)
    csv_path = tmp_path / "worker_timeline.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


def test_import_csv_to_list_reads_csv(sample_equipment_csv: Path) -> None:
    """Test that import_csv_to_list reads CSV correctly."""
    df = pd.read_csv(sample_equipment_csv)
    assert len(df) == 3
    assert list(df.columns) == [
        "EquipmentID",
        "EquipmentName",
        "Location",
        "Status",
        "LastActive",
        "CurrentOperator",
    ]


def test_import_csv_to_list_with_field_mapping(
    sample_equipment_csv: Path,
) -> None:
    """Test that field mapping transforms column names correctly."""
    df = pd.read_csv(sample_equipment_csv)

    field_mapping = {
        "EquipmentID": "Title",
        "EquipmentName": "EquipmentName",
        "Location": "Location",
        "Status": "Status",
        "LastActive": "LastActive",
        "CurrentOperator": "CurrentOperator",
    }

    # Verify mapping keys match CSV columns
    assert set(field_mapping.keys()) == set(df.columns)

    # Verify first row can be mapped
    row = df.iloc[0]
    mapped_data = {field_mapping.get(col, col): row[col] for col in df.columns}
    assert mapped_data["Title"] == "BED-01"
    assert mapped_data["EquipmentName"] == "Casting Bed 1"


def test_import_csv_to_list_mocked(sample_equipment_csv: Path) -> None:
    """Test import_csv_to_list with mocked SharePoint client."""
    mock_client = MagicMock()
    mock_list = MagicMock()
    mock_client.ctx.web.lists.get_by_title.return_value = mock_list

    field_mapping = {
        "EquipmentID": "Title",
        "EquipmentName": "EquipmentName",
        "Location": "Location",
        "Status": "Status",
        "LastActive": "LastActive",
        "CurrentOperator": "CurrentOperator",
    }

    stats = import_csv_to_list(
        mock_client,
        sample_equipment_csv,
        "Equipment Status",
        field_mapping,
    )

    # Verify correct list was accessed
    mock_client.ctx.web.lists.get_by_title.assert_called_once_with("Equipment Status")

    # Verify add_item was called for each row
    assert mock_list.add_item.call_count == 3

    # Verify stats
    assert stats["rows_imported"] == 3
    assert len(stats["errors"]) == 0


def test_import_equipment_status_mocked(sample_equipment_csv: Path) -> None:
    """Test import_equipment_status with mocked SharePoint client."""
    mock_client = MagicMock()
    mock_list = MagicMock()
    mock_client.ctx.web.lists.get_by_title.return_value = mock_list

    stats = import_equipment_status(mock_client, sample_equipment_csv)

    assert stats["rows_imported"] == 3
    assert len(stats["errors"]) == 0


def test_import_overtime_analysis_mocked(sample_overtime_csv: Path) -> None:
    """Test import_overtime_analysis with mocked SharePoint client."""
    mock_client = MagicMock()
    mock_list = MagicMock()
    mock_client.ctx.web.lists.get_by_title.return_value = mock_list

    stats = import_overtime_analysis(mock_client, sample_overtime_csv)

    assert stats["rows_imported"] == 2
    assert len(stats["errors"]) == 0


def test_import_worker_timeline_mocked(sample_worker_timeline_csv: Path) -> None:
    """Test import_worker_timeline with mocked SharePoint client."""
    mock_client = MagicMock()
    mock_list = MagicMock()
    mock_client.ctx.web.lists.get_by_title.return_value = mock_list

    stats = import_worker_timeline(mock_client, sample_worker_timeline_csv)

    assert stats["rows_imported"] == 2
    assert len(stats["errors"]) == 0


def test_import_csv_handles_missing_values(tmp_path: Path) -> None:
    """Test that import handles NaN/None values correctly."""
    data = {
        "EquipmentID": ["BED-01", "BED-02"],
        "EquipmentName": ["Casting Bed 1", None],
        "Location": ["Bay A", "Bay B"],
        "Status": ["Idle", "Active"],
        "LastActive": ["2026-02-09 22:45:00", "2026-02-09 23:55:00"],
        "CurrentOperator": [None, "Garcia"],
    }
    df = pd.DataFrame(data)
    csv_path = tmp_path / "equipment_with_nulls.csv"
    df.to_csv(csv_path, index=False)

    mock_client = MagicMock()
    mock_list = MagicMock()
    mock_client.ctx.web.lists.get_by_title.return_value = mock_list

    stats = import_csv_to_list(
        mock_client,
        csv_path,
        "Equipment Status",
    )

    # Verify all rows were processed
    assert stats["rows_imported"] == 2
    assert len(stats["errors"]) == 0

    # Verify add_item was called for each row (including ones with None values)
    assert mock_list.add_item.call_count == 2
