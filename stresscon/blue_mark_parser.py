"""Blue Mark Report spreadsheet parser.

Parses legacy (.ods/.xlsx, 2022-2025) and v2026 (.xlsx) Blue Mark Report
files into normalized dictionaries ready for SQLite insertion via BlueMarkDB.

Stresscon's Blue Mark Reports track precast concrete pieces through QA
stages.  There are ~462 daily report files across two schema versions.
"""

import calendar
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Month name lookup (case-insensitive)
# ---------------------------------------------------------------------------
_MONTH_MAP: dict[str, int] = {
    name.upper(): num for num, name in enumerate(calendar.month_name) if num
}

# ---------------------------------------------------------------------------
# Legacy column name normalisation
# ---------------------------------------------------------------------------
# Maps the many observed header spellings to canonical keys.
_LEGACY_COLUMN_MAP: dict[str, str] = {
    "pour date": "pour_date",
    "job #": "job_number",
    "job#": "job_number",
    "job number": "job_number",
    "piece #": "piece_number",
    "piece#": "piece_number",
    "piece number": "piece_number",
    "piece blue marked": "blue_marked",
    "blue marked": "blue_marked",
    "patching/cleaning": "patching_cleaning",
    "patching / cleaning": "patching_cleaning",
    "patching": "patching_cleaning",
    "post pour weld-on required": "weld_on_required",
    "weld-on required": "weld_on_required",
    "weld on required": "weld_on_required",
    "post pour weld on required": "weld_on_required",
    "ncr response": "ncr_response",
    "ncr repair": "ncr_repair",
    "ncr repair/comments": "ncr_repair",
    "comments/location": "comments",
    "comments/ location": "comments",
    "location/ comments": "comments",
    "location/comments": "comments",
    "comments": "comments",
    "architechtural finish": "architectural_finish",  # known typo
    "architectural finish": "architectural_finish",
    "architectural finishing": "architectural_finish",
    "architechtural finishing": "architectural_finish",
}

# v2026 column name normalisation
_V2026_COLUMN_MAP: dict[str, str] = {
    "job number": "job_number",
    "job #": "job_number",
    "job#": "job_number",
    "piece number": "piece_number",
    "piece #": "piece_number",
    "piece#": "piece_number",
    "production pre-pour": "production_pre_pour",
    "production pre pour": "production_pre_pour",
    "qa pre-pour": "qa_pre_pour",
    "qa pre pour": "qa_pre_pour",
    "production wythe check": "production_wythe_check",
    "qa wythe check": "qa_wythe_check",
    "production top check": "production_top_check",
}

# Legacy boolean columns (order matters for positional fallback).
_LEGACY_BOOL_COLS = [
    "blue_marked",
    "patching_cleaning",
    "weld_on_required",
    "ncr_response",
    "ncr_repair",
]

# v2026 boolean columns
_V2026_BOOL_COLS = [
    "production_pre_pour",
    "qa_pre_pour",
    "production_wythe_check",
    "qa_wythe_check",
    "production_top_check",
]

# All boolean columns across both schemas
_ALL_BOOL_COLS = _LEGACY_BOOL_COLS + ["architectural_finish"] + _V2026_BOOL_COLS


# ---------------------------------------------------------------------------
# Helper: boolean coercion
# ---------------------------------------------------------------------------
def _to_bool_int(value: object) -> int:
    """Convert a cell value to a 0/1 integer.

    Any non-empty, non-None value is truthy (the reports use "X").
    Handles pandas NA/NaN gracefully.
    """
    if value is None:
        return 0
    if isinstance(value, float) and pd.isna(value):
        return 0
    if isinstance(value, str) and value.strip() == "":
        return 0
    try:
        if pd.isna(value):
            return 0
    except (TypeError, ValueError):
        pass
    return 1


# ---------------------------------------------------------------------------
# Helper: safe integer conversion for job numbers
# ---------------------------------------------------------------------------
def _safe_job_number(value: object) -> Optional[int]:
    """Convert a job number value to int, handling floats and strings.

    Returns None if the value cannot be converted.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Helper: safe piece number normalisation
# ---------------------------------------------------------------------------
def _safe_piece_number(value: object) -> Optional[str]:
    """Normalise a piece number to a stripped string.

    Returns None if the value is empty/missing.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    # Strip trailing .0 from float-converted strings like "7134.0"
    if text.endswith(".0"):
        text = text[:-2]
    return text


# ---------------------------------------------------------------------------
# Helper: safe comments extraction
# ---------------------------------------------------------------------------
def _safe_comments(value: object) -> Optional[str]:
    """Extract a comments string, returning None for empty/NA values."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text == "" or text.lower() == "nan":
        return None
    return text


# ---------------------------------------------------------------------------
# Helper: pour date parsing
# ---------------------------------------------------------------------------
def _parse_pour_date(value: object) -> Optional[str]:
    """Convert a pour date value to ISO format string.

    Handles datetime objects, pandas Timestamps, and various string
    formats.  Returns None when the value is empty/missing.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d") if not isinstance(value, datetime) else value.date().isoformat()
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    text = str(value).strip()
    if text == "" or text.lower() == "nan" or text.lower() == "nat":
        return None
    # Try common date formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    # pandas fallback
    try:
        return pd.to_datetime(text).date().isoformat()
    except Exception:
        logger.warning("Could not parse pour date: %r", value)
        return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def extract_piece_type(piece_number: str) -> str:
    """Extract the alpha prefix from a piece number.

    Examples:
        W7104   -> W
        DT2093  -> DT
        AIW7070 -> AIW

    Returns an empty string if no alpha prefix is found.
    """
    match = re.match(r"^([A-Za-z]+)", piece_number.strip())
    return match.group(1).upper() if match else ""


def extract_bed_type(filename: str) -> Optional[str]:
    """Extract the bed type from a v2026 filename.

    v2026 files are named like 'BMD - 27.xlsx', 'S4 - 16.xlsx',
    'HICAP 30.xlsx', or 'BMD 14.xlsx'.  Legacy files use plain
    numeric names like '31.ods'.

    Returns None for legacy numeric filenames or if no bed type
    can be identified.
    """
    stem = Path(filename).stem.strip()
    # Legacy: purely numeric (possibly with parenthesised suffix like "31(1)")
    if re.match(r"^\d+(\(\d+\))?$", stem):
        return None
    # v2026: everything before the last number is the bed type
    match = re.match(r"^([A-Za-z][A-Za-z0-9]*)\s*-?\s*\d+", stem)
    if match:
        return match.group(1).strip().upper()
    return None


def infer_date_from_path(path: Path) -> date:
    """Extract the report date from a file path.

    Expected structures:
        Blue Mark Reports/2024/DECEMBER/31.xlsx      -> 2024-12-31
        Blue Mark Reports/2024/DECEMBER/31(1).xlsx    -> 2024-12-31
        Blue Mark Reports/2026/JANUARY/BMD - 27.xlsx  -> 2026-01-27

    The day is the last number in the filename stem.

    Raises:
        ValueError: If the date cannot be inferred from the path.
    """
    parts = path.parts
    # Walk backwards to find the year/month/filename components.
    # We need at minimum: .../YEAR/MONTH/filename
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None

    # Extract day from filename: handle many naming conventions:
    #   31.ods, 31(1).ods          -> 31
    #   12TH.ods, 1ST.ods, 22cnd   -> 12, 1, 22  (ordinal suffixes)
    #   may 4th.ods, may 10.ods    -> 4, 10       (month prefix)
    #   1jun.ods                   -> 1            (month suffix)
    #   BMD - 27.xlsx              -> 27           (bed type prefix)
    stem = path.stem.strip()
    # Strip ordinal suffixes (case-insensitive): TH, ST, ND, RD, CND
    cleaned = re.sub(r"(?i)(st|nd|rd|th|cnd)(\(\d+\))?$", "", stem).strip()
    # Strip known month prefixes/suffixes: "may 4", "1jun"
    cleaned = re.sub(r"(?i)^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s*", "", cleaned).strip()
    cleaned = re.sub(r"(?i)(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*$", "", cleaned).strip()
    # Now extract the last number from what remains
    day_match = re.search(r"(\d+)(?:\(\d+\))?$", cleaned)
    if not day_match:
        # Fallback: find any number in the original stem
        day_match = re.search(r"(\d+)", stem)
    if day_match:
        day = int(day_match.group(1))

    # Walk parts in reverse looking for month name and year
    for part in reversed(parts[:-1]):  # exclude filename
        part_upper = part.strip().upper()
        if part_upper in _MONTH_MAP and month is None:
            month = _MONTH_MAP[part_upper]
        elif part.strip().isdigit() and year is None:
            candidate = int(part.strip())
            if 2000 <= candidate <= 2099:
                year = candidate

    if year is None or month is None or day is None:
        raise ValueError(f"Cannot infer date from path: {path}")

    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ValueError(f"Invalid date components from path {path}: {year}-{month}-{day}") from exc


# ---------------------------------------------------------------------------
# Schema detection
# ---------------------------------------------------------------------------

def _read_spreadsheet(path: Path, nrows: Optional[int] = None, header: Optional[int] = 0) -> pd.DataFrame:
    """Read a spreadsheet file (.ods or .xlsx) into a DataFrame.

    Automatically selects the appropriate pandas engine based on
    file extension.
    """
    suffix = path.suffix.lower()
    kwargs: dict = {}
    if nrows is not None:
        kwargs["nrows"] = nrows
    if header is not None:
        kwargs["header"] = header
    else:
        kwargs["header"] = None

    if suffix == ".ods":
        return pd.read_excel(path, engine="odf", **kwargs)
    elif suffix in (".xlsx", ".xls"):
        return pd.read_excel(path, engine="openpyxl", **kwargs)
    else:
        raise ValueError(f"Unsupported file extension: {suffix}")


def _normalise_header(col: object) -> str:
    """Lowercase and strip a column header, collapsing whitespace."""
    text = str(col).strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def detect_schema(path: Path) -> str:
    """Detect whether a file uses 'legacy' or 'v2026' schema.

    Reads the first few rows and inspects column headers.

    Returns:
        'legacy' or 'v2026'.

    Raises:
        ValueError: If the schema cannot be determined.
    """
    # Read raw (no header interpretation) so we can inspect rows
    try:
        raw = _read_spreadsheet(path, nrows=5, header=None)
    except Exception as exc:
        raise ValueError(f"Cannot read file to detect schema: {path}") from exc

    if raw.empty:
        raise ValueError(f"File is empty: {path}")

    # Check both row 0 and row 1 for headers (counter column case)
    for row_idx in range(min(3, len(raw))):
        row_values = [_normalise_header(v) for v in raw.iloc[row_idx] if pd.notna(v)]
        joined = " ".join(row_values)

        # v2026 distinctive headers
        if "wythe check" in joined or "production pre" in joined:
            return "v2026"
        # Legacy distinctive headers
        if "pour date" in joined or "blue marked" in joined or "piece blue" in joined:
            return "legacy"

    # Fallback: check filename pattern
    bed = extract_bed_type(path.name)
    if bed is not None:
        return "v2026"

    # Default to legacy for numeric filenames
    if re.match(r"^\d+", path.stem):
        return "legacy"

    raise ValueError(f"Cannot determine schema for: {path}")


# ---------------------------------------------------------------------------
# Legacy parser
# ---------------------------------------------------------------------------

def _detect_header_row(raw: pd.DataFrame) -> int:
    """Find the row index containing column headers in a raw DataFrame.

    The QA template sometimes has a counter in column A, pushing
    headers into row 0 or row 1.  We look for the row containing
    recognisable header text.
    """
    for row_idx in range(min(5, len(raw))):
        row_values = [_normalise_header(v) for v in raw.iloc[row_idx] if pd.notna(v)]
        joined = " ".join(row_values)
        if "pour date" in joined or "job" in joined or "piece" in joined or "blue marked" in joined or "wythe" in joined:
            return row_idx
    return 0


def _has_counter_column(raw: pd.DataFrame, header_row: int) -> bool:
    """Detect if column A is a row counter rather than data.

    The QA paperwork template has a numeric counter in column A,
    shifting data columns to B-J.
    """
    first_header = _normalise_header(raw.iloc[header_row, 0])
    # If the first header is a number or unnamed, it's a counter
    if first_header in ("", "nan", "none"):
        return True
    try:
        float(first_header)
        return True
    except (ValueError, TypeError):
        pass
    # If it doesn't match any known header, it's likely a counter
    if first_header not in _LEGACY_COLUMN_MAP and first_header not in _V2026_COLUMN_MAP:
        # Check if it looks like a number label
        if re.match(r"^\d+$", first_header):
            return True
    return False


def parse_legacy_file(path: Path, report_date: date) -> list[dict]:
    """Parse a legacy format Blue Mark Report file (2022 - April 2025).

    Args:
        path: Path to the .ods or .xlsx file.
        report_date: The report date to attach to each record.

    Returns:
        List of normalised record dicts ready for SQLite insertion.
    """
    logger.info("Parsing legacy file: %s", path)

    try:
        raw = _read_spreadsheet(path, header=None)
    except Exception:
        logger.exception("Failed to read file: %s", path)
        return []

    if raw.empty or len(raw) < 2:
        logger.warning("File is empty or too short: %s", path)
        return []

    # Locate the header row
    header_row = _detect_header_row(raw)
    has_counter = _has_counter_column(raw, header_row)

    # Extract headers
    headers_raw = raw.iloc[header_row].tolist()
    if has_counter:
        headers_raw = headers_raw[1:]  # skip counter column

    # Normalise headers to canonical keys
    col_mapping: list[Optional[str]] = []
    for h in headers_raw:
        key = _normalise_header(h)
        canonical = _LEGACY_COLUMN_MAP.get(key)
        col_mapping.append(canonical)

    # Data starts after the header row.  Skip an optional empty row.
    data_start = header_row + 1
    if data_start < len(raw):
        # Check if the row immediately after headers is completely empty
        next_row = raw.iloc[data_start]
        if next_row.isna().all():
            data_start += 1

    records: list[dict] = []
    source_file = _relative_source_path(path)

    for row_idx in range(data_start, len(raw)):
        row = raw.iloc[row_idx].tolist()
        if has_counter:
            row = row[1:]  # skip counter column

        # Skip fully empty rows
        if all(pd.isna(v) if not isinstance(v, str) else v.strip() == "" for v in row):
            continue

        # Build record from column mapping
        record: dict = {
            "report_date": report_date.isoformat(),
            "pour_date": None,
            "job_number": None,
            "piece_number": None,
            "piece_type": None,
            "bed_type": None,
            "blue_marked": 0,
            "patching_cleaning": 0,
            "weld_on_required": 0,
            "ncr_response": 0,
            "ncr_repair": 0,
            "architectural_finish": 0,
            "production_pre_pour": 0,
            "qa_pre_pour": 0,
            "production_wythe_check": 0,
            "qa_wythe_check": 0,
            "production_top_check": 0,
            "comments": None,
            "source_file": source_file,
            "schema_version": "legacy",
        }

        # Collect overflow comments from beyond mapped columns
        overflow_comments: list[str] = []

        for col_idx, value in enumerate(row):
            if col_idx < len(col_mapping):
                canonical = col_mapping[col_idx]
                if canonical is None:
                    # Unmapped column -- treat as potential overflow comment
                    comment_text = _safe_comments(value)
                    if comment_text:
                        overflow_comments.append(comment_text)
                    continue

                if canonical == "pour_date":
                    record["pour_date"] = _parse_pour_date(value)
                elif canonical == "job_number":
                    record["job_number"] = _safe_job_number(value)
                elif canonical == "piece_number":
                    record["piece_number"] = _safe_piece_number(value)
                elif canonical == "comments":
                    record["comments"] = _safe_comments(value)
                elif canonical in _ALL_BOOL_COLS:
                    record[canonical] = _to_bool_int(value)
            else:
                # Columns beyond the defined headers: overflow comments
                comment_text = _safe_comments(value)
                if comment_text:
                    overflow_comments.append(comment_text)

        # Merge overflow comments
        if overflow_comments:
            existing = record.get("comments")
            all_comments = ([existing] if existing else []) + overflow_comments
            record["comments"] = " | ".join(all_comments)

        # Validate minimum required fields
        if record["job_number"] is None or record["piece_number"] is None:
            logger.debug(
                "Skipping row %d in %s: missing job_number or piece_number",
                row_idx, path,
            )
            continue

        # Derived fields
        record["piece_type"] = extract_piece_type(record["piece_number"])
        record["bed_type"] = extract_bed_type(path.name)

        records.append(record)

    logger.info("Parsed %d records from legacy file: %s", len(records), path)
    return records


# ---------------------------------------------------------------------------
# v2026 parser
# ---------------------------------------------------------------------------

def parse_v2026_file(path: Path, report_date: date) -> list[dict]:
    """Parse a v2026 format Blue Mark Report file (January 2026+).

    Args:
        path: Path to the .xlsx file.
        report_date: The report date to attach to each record.

    Returns:
        List of normalised record dicts ready for SQLite insertion.
    """
    logger.info("Parsing v2026 file: %s", path)

    try:
        raw = _read_spreadsheet(path, header=None)
    except Exception:
        logger.exception("Failed to read file: %s", path)
        return []

    if raw.empty or len(raw) < 2:
        logger.warning("File is empty or too short: %s", path)
        return []

    # Locate the header row
    header_row = _detect_header_row(raw)

    # Extract and normalise headers
    headers_raw = raw.iloc[header_row].tolist()
    col_mapping: list[Optional[str]] = []
    for h in headers_raw:
        key = _normalise_header(h)
        canonical = _V2026_COLUMN_MAP.get(key)
        col_mapping.append(canonical)

    # Data starts after the header row
    data_start = header_row + 1
    if data_start < len(raw):
        next_row = raw.iloc[data_start]
        if next_row.isna().all():
            data_start += 1

    bed_type = extract_bed_type(path.name)
    source_file = _relative_source_path(path)
    records: list[dict] = []

    for row_idx in range(data_start, len(raw)):
        row = raw.iloc[row_idx].tolist()

        # Skip fully empty rows
        if all(pd.isna(v) if not isinstance(v, str) else v.strip() == "" for v in row):
            continue

        record: dict = {
            "report_date": report_date.isoformat(),
            "pour_date": None,
            "job_number": None,
            "piece_number": None,
            "piece_type": None,
            "bed_type": bed_type,
            "blue_marked": 0,
            "patching_cleaning": 0,
            "weld_on_required": 0,
            "ncr_response": 0,
            "ncr_repair": 0,
            "architectural_finish": 0,
            "production_pre_pour": 0,
            "qa_pre_pour": 0,
            "production_wythe_check": 0,
            "qa_wythe_check": 0,
            "production_top_check": 0,
            "comments": None,
            "source_file": source_file,
            "schema_version": "v2026",
        }

        for col_idx, value in enumerate(row):
            if col_idx >= len(col_mapping):
                break
            canonical = col_mapping[col_idx]
            if canonical is None:
                continue

            if canonical == "job_number":
                record["job_number"] = _safe_job_number(value)
            elif canonical == "piece_number":
                record["piece_number"] = _safe_piece_number(value)
            elif canonical in _ALL_BOOL_COLS:
                record[canonical] = _to_bool_int(value)

        # Validate minimum required fields
        if record["job_number"] is None or record["piece_number"] is None:
            logger.debug(
                "Skipping row %d in %s: missing job_number or piece_number",
                row_idx, path,
            )
            continue

        # Derived fields
        record["piece_type"] = extract_piece_type(record["piece_number"])

        records.append(record)

    logger.info("Parsed %d records from v2026 file: %s", len(records), path)
    return records


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------

def parse_file(path: Path) -> list[dict]:
    """Auto-detect schema and parse a Blue Mark Report file.

    Infers the report date from the file path and dispatches to
    the appropriate schema-specific parser.

    Args:
        path: Path to the spreadsheet file.

    Returns:
        List of normalised record dicts ready for SQLite insertion.
        Returns an empty list on error.
    """
    path = Path(path)

    try:
        report_date = infer_date_from_path(path)
    except ValueError:
        logger.error("Cannot infer report date from path: %s", path)
        return []

    try:
        schema = detect_schema(path)
    except ValueError:
        logger.error("Cannot detect schema for file: %s", path)
        return []

    if schema == "v2026":
        return parse_v2026_file(path, report_date)
    else:
        return parse_legacy_file(path, report_date)


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------

def _relative_source_path(path: Path) -> str:
    """Return a portable relative source path for storage.

    Tries to produce a path relative to a 'Blue Mark Reports' ancestor
    directory.  Falls back to just the filename.
    """
    parts = path.parts
    for i, part in enumerate(parts):
        if part.lower() == "blue mark reports":
            return str(Path(*parts[i:]))
    # Fallback: return last 3-4 components if available
    tail = parts[-min(4, len(parts)):]
    return str(Path(*tail))
