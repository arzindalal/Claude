"""
Excel workbook parser for DOORS, Cradle, and generic multi-sheet exports.

Sheet type is detected first from the sheet name, then from column headers.
Safety Goal / FSR / TSR / SSR sheets are normalised to the Requirement model
with the appropriate req_type value so the rest of the pipeline handles them
uniformly.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .csv_parser import (
    REQ_COLUMN_ALIASES,
    TC_COLUMN_ALIASES,
    DEFECT_COLUMN_ALIASES,
    _find_column,
    _get,
    _split_ids,
    _resolve_tc_status,
    _LEVEL_NORMALISE_MAP,
    detect_artifact_type,
)


# ── Sheet-type detection ──────────────────────────────────────────────────────

_SHEET_HINTS: dict[str, list[str]] = {
    "safety_goals": ["safety goal", "safety goals", "hazard", "hara", "sg"],
    "fsr":          ["fsr", "functional safety req"],
    "tsr":          ["tsr", "technical safety", "tech safety"],
    "ssr":          ["ssr", "software safety", "sw safety"],
    "requirements": ["requirement", "req", "sys req", "customer req", "functional req"],
    "test_cases":   ["test case", "test plan", "test spec", "tc", "tests"],
    "defects":      ["defect", "issue", "bug", "jira", "nonconformity"],
}

_SAFETY_TYPE_MAP = {
    "safety_goals": "Safety Goal",
    "fsr": "FSR",
    "tsr": "TSR",
    "ssr": "SSR",
}


def _detect_sheet_type_by_name(sheet_name: str) -> Optional[str]:
    lower = sheet_name.lower().strip()
    for sheet_type, hints in _SHEET_HINTS.items():
        if any(hint in lower for hint in hints):
            return sheet_type
    return None


def _detect_sheet_type_by_columns(df: pd.DataFrame) -> Optional[str]:
    cols = {c.lower().strip() for c in df.columns}
    artifact_type = detect_artifact_type(cols)
    # detect_artifact_type falls back to "requirements" for unknown — only return
    # that if there are columns that actually look like requirements.
    if artifact_type == "requirements":
        if not (cols & {"asil", "asil_level", "asil level", "object_text",
                        "requirement_text", "req_id", "requirement_id", "object_id",
                        "id", "text", "statement"}):
            return None
    return artifact_type


# ── Per-sheet parsing helpers ─────────────────────────────────────────────────

def _parse_requirement_df(
    df: pd.DataFrame, source_file: str, req_type_override: Optional[str] = None
) -> list[dict]:
    df = df.copy()
    df.columns = df.columns.str.strip()
    col = {field: _find_column(df, aliases) for field, aliases in REQ_COLUMN_ALIASES.items()}

    if col["id"] is None or col["text"] is None:
        return []

    records = []
    for _, row in df.iterrows():
        req_id = _get(row, col["id"])
        if not req_id:
            continue
        records.append({
            "id": req_id,
            "text": _get(row, col["text"]),
            "title": _get(row, col["title"]),
            "asil_level": _get(row, col["asil_level"], "QM"),
            "req_type": req_type_override or _get(row, col["req_type"], "Functional"),
            "status": _get(row, col["status"], "Active"),
            "parent_id": _get(row, col["parent_id"]) or None,
            "source_file": source_file,
        })
    return records


def _parse_test_case_df(df: pd.DataFrame, source_file: str) -> list[dict]:
    df = df.copy()
    df.columns = df.columns.str.strip()
    col = {field: _find_column(df, aliases) for field, aliases in TC_COLUMN_ALIASES.items()}

    if col["id"] is None or col["title"] is None:
        return []

    records = []
    for _, row in df.iterrows():
        tc_id = _get(row, col["id"])
        if not tc_id:
            continue
        linked_raw = _get(row, col["linked_req_ids"])
        lifecycle_state, verdict = _resolve_tc_status(row, col)
        raw_level = _get(row, col["level"], "SW Qualification Testing")
        level = _LEVEL_NORMALISE_MAP.get(raw_level.lower(), raw_level)
        records.append({
            "id": tc_id,
            "title": _get(row, col["title"]),
            "objective": _get(row, col["objective"]),
            "preconditions": _get(row, col["preconditions"]),
            "steps": _get(row, col["steps"]),
            "expected_result": _get(row, col["expected_result"]),
            "level": level,
            "verification_method": _get(row, col["verification_method"], "Dynamic Test"),
            "lifecycle_state": lifecycle_state,
            "verdict": verdict,
            "linked_req_ids": _split_ids(linked_raw) if linked_raw else [],
            "source_file": source_file,
        })
    return records


def _parse_defect_df(df: pd.DataFrame, source_file: str) -> list[dict]:
    df = df.copy()
    df.columns = df.columns.str.strip()
    col = {field: _find_column(df, aliases) for field, aliases in DEFECT_COLUMN_ALIASES.items()}

    if col["id"] is None or col["summary"] is None:
        return []

    records = []
    for _, row in df.iterrows():
        defect_id = _get(row, col["id"])
        if not defect_id:
            continue
        linked_raw = _get(row, col["linked_req_ids"])
        records.append({
            "id": defect_id,
            "summary": _get(row, col["summary"]),
            "description": _get(row, col["description"]),
            "severity": _get(row, col["severity"], "Medium"),
            "status": _get(row, col["status"], "Open"),
            "linked_req_ids": _split_ids(linked_raw) if linked_raw else [],
            "source_file": source_file,
        })
    return records


# ── Public API ────────────────────────────────────────────────────────────────

def parse_excel(file_path: str) -> dict[str, list[dict]]:
    """Parse an Excel workbook and return normalised artifact records grouped by type.

    Returns:
        {
            "requirements": [...],   # includes SG, FSR, TSR, SSR normalised records
            "test_cases":   [...],
            "defects":      [...],
        }
    """
    result: dict[str, list[dict]] = {
        "requirements": [],
        "test_cases": [],
        "defects": [],
    }

    with pd.ExcelFile(file_path) as xl:
        for sheet_name in xl.sheet_names:
            df: pd.DataFrame = xl.parse(sheet_name, dtype=str)  # type: ignore[assignment]

            # Skip truly empty sheets and header-only sheets (no data rows)
            if not isinstance(df, pd.DataFrame) or len(df) == 0:
                continue

            sheet_type = (
                _detect_sheet_type_by_name(sheet_name)
                or _detect_sheet_type_by_columns(df)
            )
            if sheet_type is None:
                continue

            source = str(file_path)

            if sheet_type in _SAFETY_TYPE_MAP:
                records = _parse_requirement_df(
                    df, source, req_type_override=_SAFETY_TYPE_MAP[sheet_type]
                )
                result["requirements"].extend(records)
            elif sheet_type == "requirements":
                result["requirements"].extend(_parse_requirement_df(df, source))
            elif sheet_type == "test_cases":
                result["test_cases"].extend(_parse_test_case_df(df, source))
            elif sheet_type == "defects":
                result["defects"].extend(_parse_defect_df(df, source))

    return result
