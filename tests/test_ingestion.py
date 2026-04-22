"""Smoke test — parsers turn the sample CSVs into typed records without touching Chroma."""

from __future__ import annotations

from pathlib import Path

from src.kb.models import (
    ASIL,
    DefectStatus,
    ReqLevel,
    TestLevel,
)
from src.kb.parsers.tabular import (
    parse_defects,
    parse_requirements,
    parse_test_cases,
)

SAMPLES = Path(__file__).parent.parent / "samples"


def test_parse_requirements_sample():
    reqs = parse_requirements(SAMPLES / "requirements.csv")
    by_id = {r.id: r for r in reqs}

    assert "SG-01" in by_id
    assert by_id["SG-01"].level is ReqLevel.SAFETY_GOAL
    assert by_id["SG-01"].asil is ASIL.D

    assert by_id["TSR-01"].parent_id == "SG-01"
    assert by_id["SSR-01"].parent_id == "TSR-01"

    # QM-level requirement parses as QM.
    assert by_id["CUST-REQ-101"].asil is ASIL.QM


def test_parse_test_cases_sample():
    tcs = parse_test_cases(SAMPLES / "test_cases.csv")
    by_id = {t.id: t for t in tcs}

    assert by_id["TC-SG-01-01"].level is TestLevel.VALIDATION
    # Multi-ID trace field: "SG-01;TSR-01" → two IDs.
    assert set(by_id["TC-SG-01-01"].verifies_req_ids) == {"SG-01", "TSR-01"}

    assert by_id["TC-SYS-042-01"].asil_coverage_hint.startswith("ASIL-C")


def test_parse_defects_sample():
    defects = parse_defects(SAMPLES / "defects.csv")
    by_id = {d.id: d for d in defects}

    assert by_id["DEF-1001"].status is DefectStatus.OPEN
    assert "SYS-REQ-043" in by_id["DEF-1001"].against_req_ids
    assert by_id["DEF-1002"].status is DefectStatus.IN_PROGRESS
