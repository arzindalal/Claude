"""
Flexible CSV parser for requirements, test cases, and defects.

Handles varied column naming conventions from DOORS, Cradle, Jira, and
plain Excel-exported CSV files. Column matching is case-insensitive.
"""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd


# ── Column alias tables ───────────────────────────────────────────────────────
# Each list is ordered from most-specific to most-generic so the first
# match wins and avoids false positives.

REQ_COLUMN_ALIASES: dict[str, list[str]] = {
    "id":          ["req_id", "requirement_id", "object_id", "identifier", "id", "#"],
    "text":        ["requirement_text", "object_text", "statement", "description", "text", "body"],
    "title":       ["short_description", "summary", "title", "name"],
    "asil_level":  ["asil_level", "asil level", "safety_level", "asil"],
    "req_type":    ["req_type", "object_type", "requirement_type", "category", "type"],
    "status":      ["state", "status"],
    "parent_id":   ["parent_object_id", "derived_from", "parent_id", "parent"],
}

TC_COLUMN_ALIASES: dict[str, list[str]] = {
    "id":                  ["test_id", "tc_id", "test case id", "testcase_id", "id"],
    "title":               ["test_name", "summary", "title", "name"],
    "objective":           ["purpose", "objective", "description"],
    "preconditions":       ["pre-conditions", "precondition", "preconditions", "setup"],
    "steps":               ["test_steps", "procedure", "actions", "steps"],
    "expected_result":     ["expected results", "pass criteria", "expected_result", "expected result"],
    "level":               ["test_level", "test level", "level", "type"],
    "verification_method": ["verification_method", "verification method", "method", "test_method"],
    "lifecycle_state":     ["lifecycle_state", "lifecycle state", "test_state"],
    "verdict":             ["verdict", "test_result"],
    "status":              ["result", "state", "status"],  # legacy fallback — mapped to lifecycle_state+verdict
    "linked_req_ids":      ["requirement_id", "covers", "traces_to", "linked_req_ids", "req_id"],
}

# Note: "description" deliberately absent from "summary" aliases to prevent
# a Jira CSV's single "description" column being consumed by summary and
# leaving the description field empty.
DEFECT_COLUMN_ALIASES: dict[str, list[str]] = {
    "id":              ["issue_id", "key", "defect_id", "jira_id", "id"],
    "summary":         ["title", "subject", "summary"],
    "description":     ["details", "body", "comment", "description"],
    "severity":        ["impact", "priority", "severity"],
    "status":          ["resolution", "state", "status"],
    "linked_req_ids":  ["requirement_id", "affects", "relates_to", "linked_req_ids", "req_id"],
}

# Maps a legacy "status" cell value to (lifecycle_state, verdict).
_LEGACY_TC_STATUS_MAP: dict[str, tuple[str, str]] = {
    "open":     ("Draft",    "Not Run"),
    "draft":    ("Draft",    "Not Run"),
    "ready":    ("Ready",    "Not Run"),
    "executed": ("Executed", "Not Run"),
    "pass":     ("Executed", "Pass"),
    "passed":   ("Executed", "Pass"),
    "fail":     ("Executed", "Fail"),
    "failed":   ("Executed", "Fail"),
    "blocked":  ("Executed", "Blocked"),
    "n/a":      ("Executed", "N/A"),
}

# Maps common level strings to ISO 26262 Part 6 test level values.
_LEVEL_NORMALISE_MAP: dict[str, str] = {
    "unit":              "SW Unit Testing",
    "sw unit":           "SW Unit Testing",
    "sw unit testing":   "SW Unit Testing",
    "integration":       "SW Integration Testing",
    "sw integration":    "SW Integration Testing",
    "system":            "SW Qualification Testing",
    "sw qualification":  "SW Qualification Testing",
    "acceptance":        "SW Qualification Testing",
    "hw/sw integration": "HW/SW Integration Testing",
    "hw sw integration": "HW/SW Integration Testing",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_column(df: pd.DataFrame, aliases: list[str]) -> Optional[str]:
    """Return the first df column that matches any alias (case-insensitive).

    Iterates df.columns in order so the first occurrence wins when duplicate
    case-folded names are present.
    """
    lower_to_original: dict[str, str] = {}
    for col in df.columns:
        lower = col.lower()
        if lower not in lower_to_original:
            lower_to_original[lower] = col

    for alias in aliases:
        match = lower_to_original.get(alias.lower())
        if match is not None:
            return match
    return None


def _get(row: pd.Series, col: Optional[str], default: str = "") -> str:
    if col is None or col not in row.index:
        return default
    val = row[col]
    return str(val).strip() if pd.notna(val) else default


def _split_ids(raw: str) -> list[str]:
    """Split a cell containing comma-, semicolon-, or pipe-separated IDs."""
    return [part.strip() for part in re.split(r"[,;|]", raw) if part.strip()]


def detect_artifact_type(columns: set[str]) -> str:
    """Infer artifact type from a set of lower-cased column names.

    Used by both the CSV ingest dispatcher and the Excel sheet classifier
    to avoid duplicating detection logic.
    """
    if columns & {"steps", "test_steps", "procedure", "expected_result",
                  "expected result", "pass criteria"}:
        return "test_cases"
    if columns & {"severity", "resolution", "issue_id", "jira_id"}:
        return "defects"
    return "requirements"


# ── Public parsers ────────────────────────────────────────────────────────────

def parse_requirements_csv(file_path: str) -> list[dict]:
    """Parse a requirements CSV and return a list of normalised requirement dicts.

    Raises ValueError if mandatory columns (id, text) cannot be found.
    """
    df = pd.read_csv(file_path, dtype=str)
    df.columns = df.columns.str.strip()

    col = {field: _find_column(df, aliases) for field, aliases in REQ_COLUMN_ALIASES.items()}

    if col["id"] is None or col["text"] is None:
        raise ValueError(
            f"CSV '{file_path}' is missing required columns 'id' and/or 'text'. "
            f"Found columns: {list(df.columns)}"
        )

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
            "req_type": _get(row, col["req_type"], "Functional"),
            "status": _get(row, col["status"], "Active"),
            "parent_id": _get(row, col["parent_id"]) or None,
            "source_file": str(file_path),
        })
    return records


def parse_test_cases_csv(file_path: str) -> list[dict]:
    """Parse a test-cases CSV and return a list of normalised test-case dicts."""
    df = pd.read_csv(file_path, dtype=str)
    df.columns = df.columns.str.strip()

    col = {field: _find_column(df, aliases) for field, aliases in TC_COLUMN_ALIASES.items()}

    if col["id"] is None or col["title"] is None:
        raise ValueError(
            f"CSV '{file_path}' is missing required columns 'id' and/or 'title'. "
            f"Found columns: {list(df.columns)}"
        )

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
            "source_file": str(file_path),
        })
    return records


def _resolve_tc_status(row: pd.Series, col: dict) -> tuple[str, str]:
    """Return (lifecycle_state, verdict) from explicit columns or legacy status mapping."""
    explicit_state = _get(row, col.get("lifecycle_state"))
    explicit_verdict = _get(row, col.get("verdict"))
    if explicit_state:
        return explicit_state, explicit_verdict or "Not Run"
    legacy = _get(row, col.get("status"), "open").lower()
    return _LEGACY_TC_STATUS_MAP.get(legacy, ("Draft", "Not Run"))


def parse_defects_csv(file_path: str) -> list[dict]:
    """Parse a defects/issues CSV and return a list of normalised defect dicts."""
    df = pd.read_csv(file_path, dtype=str)
    df.columns = df.columns.str.strip()

    col = {field: _find_column(df, aliases) for field, aliases in DEFECT_COLUMN_ALIASES.items()}

    if col["id"] is None or col["summary"] is None:
        raise ValueError(
            f"CSV '{file_path}' is missing required columns 'id' and/or 'summary'. "
            f"Found columns: {list(df.columns)}"
        )

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
            "source_file": str(file_path),
        })
    return records
