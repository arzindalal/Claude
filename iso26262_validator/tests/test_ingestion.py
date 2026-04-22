"""
Tests for Phase 1: knowledge-base ingestion.

Covers:
  - CSV parsers (happy path, alternate column names, missing mandatory columns)
  - SQLite upsert logic (new vs. update, no-duplicate guarantee)
  - Relationship wiring (Requirement ↔ TestCase, Requirement ↔ Defect)
  - Embedder mock to isolate DB logic from heavy ML dependencies
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pytest

from kb_ingestor.database import get_engine, get_session
from kb_ingestor.ingest import ingest_defects, ingest_requirements, ingest_test_cases
from kb_ingestor.models import Defect, Requirement, TestCase
from kb_ingestor.parsers.csv_parser import (
    parse_defects_csv,
    parse_requirements_csv,
    parse_test_cases_csv,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _NullEmbedder:
    """Stand-in embedder that discards all data — avoids downloading ML models."""
    def add_requirements(self, _): pass
    def add_test_cases(self, _): pass
    def add_defects(self, _): pass
    def counts(self): return {"requirements": 0, "test_cases": 0, "defects": 0}


@pytest.fixture
def embedder():
    return _NullEmbedder()


@pytest.fixture
def db_session(tmp_path):
    engine = get_engine(str(tmp_path / "test.sqlite"))
    session = get_session(engine)
    yield session
    session.close()


@pytest.fixture
def req_csv(tmp_path) -> str:
    f = tmp_path / "requirements.csv"
    with open(f, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "text", "title", "asil_level", "req_type", "status", "parent_id"])
        w.writerow(["REQ-001", "The system shall respond within 50ms to any input.", "Response Time", "B", "Functional", "Active", ""])
        w.writerow(["REQ-002", "The system shall detect sensor failure and enter safe state.", "Sensor Failure Detection", "C", "Safety", "Active", ""])
        w.writerow(["SG-001", "Prevent unintended vehicle acceleration.", "Unintended Accel Prevention", "D", "Safety Goal", "Active", ""])
        w.writerow(["TSR-001", "ECU shall monitor APS voltage at 10ms rate.", "APS Monitoring", "D", "TSR", "Active", "SG-001"])
    return str(f)


@pytest.fixture
def tc_csv(tmp_path) -> str:
    f = tmp_path / "test_cases.csv"
    with open(f, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "title", "steps", "expected_result", "level", "status", "linked_req_ids"])
        w.writerow(["TC-001", "Verify 50ms response", "1. Apply input\n2. Measure", "Response ≤ 50ms", "System", "Open", "REQ-001"])
        w.writerow(["TC-002", "Verify safe state on fault", "1. Inject fault\n2. Observe", "Safe state entered within 20ms", "System", "Open", "REQ-002"])
        w.writerow(["TC-003", "Verify APS monitoring rate", "1. Sample APS\n2. Check interval", "Sample interval ≤ 10ms", "System", "Open", "TSR-001"])
    return str(f)


@pytest.fixture
def defect_csv(tmp_path) -> str:
    f = tmp_path / "defects.csv"
    with open(f, "w", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["id", "summary", "description", "severity", "status", "linked_req_ids"])
        w.writerow(["JIRA-001", "Response time 62ms on cold start", "First event takes 62ms", "High", "Open", "REQ-001"])
        w.writerow(["JIRA-002", "Safe state reached in 28ms (spec 20ms)", "8ms overshoot under load", "Critical", "Open", "REQ-002,TSR-001"])
    return str(f)


# ── CSV parser tests ──────────────────────────────────────────────────────────

class TestRequirementsCSVParser:
    def test_parses_all_rows(self, req_csv):
        records = parse_requirements_csv(req_csv)
        assert len(records) == 4

    def test_field_values(self, req_csv):
        records = parse_requirements_csv(req_csv)
        r = records[0]
        assert r["id"] == "REQ-001"
        assert "50ms" in r["text"]
        assert r["asil_level"] == "B"
        assert r["req_type"] == "Functional"
        assert r["status"] == "Active"
        assert r["parent_id"] is None

    def test_parent_id_preserved(self, req_csv):
        records = parse_requirements_csv(req_csv)
        tsr = next(r for r in records if r["id"] == "TSR-001")
        assert tsr["parent_id"] == "SG-001"

    def test_alternate_column_names(self, tmp_path):
        """DOORS-style column names (Object_ID, Object_Text, ASIL Level) must be accepted."""
        f = tmp_path / "doors.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["Object_ID", "Object_Text", "ASIL Level", "State"])
            w.writerow(["SYS-001", "System shall boot within 2s.", "A", "Active"])
        records = parse_requirements_csv(str(f))
        assert len(records) == 1
        assert records[0]["id"] == "SYS-001"
        assert records[0]["asil_level"] == "A"

    def test_missing_mandatory_columns_raises(self, tmp_path):
        f = tmp_path / "bad.csv"
        with open(f, "w") as fp:
            fp.write("title,description\nFoo,Bar\n")
        with pytest.raises(ValueError, match="missing required columns"):
            parse_requirements_csv(str(f))

    def test_empty_id_rows_skipped(self, tmp_path):
        f = tmp_path / "sparse.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "text"])
            w.writerow(["REQ-001", "Valid requirement"])
            w.writerow(["", "Row with no ID should be skipped"])
        records = parse_requirements_csv(str(f))
        assert len(records) == 1


class TestTestCasesCSVParser:
    def test_parses_all_rows(self, tc_csv):
        records = parse_test_cases_csv(tc_csv)
        assert len(records) == 3

    def test_linked_req_ids_parsed(self, tc_csv):
        records = parse_test_cases_csv(tc_csv)
        assert records[0]["linked_req_ids"] == ["REQ-001"]

    def test_multi_link_ids_parsed(self, tmp_path):
        """Comma, semicolon, and pipe separators must all be handled."""
        f = tmp_path / "tc.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "title", "linked_req_ids"])
            w.writerow(["TC-X", "Multi-link test", "REQ-001;REQ-002|REQ-003"])
        records = parse_test_cases_csv(str(f))
        assert records[0]["linked_req_ids"] == ["REQ-001", "REQ-002", "REQ-003"]

    def test_missing_mandatory_columns_raises(self, tmp_path):
        f = tmp_path / "bad.csv"
        with open(f, "w") as fp:
            fp.write("steps,expected_result\nDo X,Result Y\n")
        with pytest.raises(ValueError, match="missing required columns"):
            parse_test_cases_csv(str(f))


class TestDefectsCSVParser:
    def test_parses_all_rows(self, defect_csv):
        records = parse_defects_csv(defect_csv)
        assert len(records) == 2

    def test_field_values(self, defect_csv):
        records = parse_defects_csv(defect_csv)
        assert records[0]["id"] == "JIRA-001"
        assert records[0]["severity"] == "High"
        assert records[0]["status"] == "Open"

    def test_multi_linked_req_ids(self, defect_csv):
        records = parse_defects_csv(defect_csv)
        assert set(records[1]["linked_req_ids"]) == {"REQ-002", "TSR-001"}


# ── Ingestion + SQLite tests ──────────────────────────────────────────────────

class TestRequirementsIngestion:
    def test_inserts_new_records(self, req_csv, db_session, embedder):
        records = parse_requirements_csv(req_csv)
        count = ingest_requirements(records, db_session, embedder)
        assert count == 4

    def test_records_retrievable(self, req_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        req = db_session.get(Requirement, "REQ-001")
        assert req is not None
        assert req.asil_level == "B"
        assert req.req_type == "Functional"

    def test_safety_chain_parent_id_stored(self, req_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        tsr = db_session.get(Requirement, "TSR-001")
        assert tsr.parent_id == "SG-001"

    def test_upsert_does_not_duplicate(self, req_csv, db_session, embedder):
        records = parse_requirements_csv(req_csv)
        ingest_requirements(records, db_session, embedder)
        second_count = ingest_requirements(records, db_session, embedder)
        assert second_count == 0
        assert db_session.query(Requirement).count() == 4

    def test_upsert_updates_existing_field(self, req_csv, db_session, embedder):
        records = parse_requirements_csv(req_csv)
        ingest_requirements(records, db_session, embedder)

        # Modify status in the record and re-ingest
        updated = [dict(r) for r in records]
        updated[0]["status"] = "Deprecated"
        ingest_requirements(updated, db_session, embedder)

        req = db_session.get(Requirement, "REQ-001")
        assert req.status == "Deprecated"


class TestTestCaseIngestion:
    def _seed_reqs(self, req_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)

    def test_inserts_new_records(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        count = ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        assert count == 3

    def test_links_requirement_to_test_case(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)

        req = db_session.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 1
        assert req.test_cases[0].id == "TC-001"

    def test_upsert_does_not_duplicate_links(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        records = parse_test_cases_csv(tc_csv)
        ingest_test_cases(records, db_session, embedder)
        ingest_test_cases(records, db_session, embedder)

        req = db_session.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 1

    def test_unresolved_req_link_is_silently_skipped(self, tc_csv, db_session, embedder):
        """Test cases with links to non-existent requirements must not crash."""
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        assert db_session.query(TestCase).count() == 3


class TestDefectIngestion:
    def _seed_reqs(self, req_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)

    def test_inserts_new_records(self, req_csv, defect_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        count = ingest_defects(parse_defects_csv(defect_csv), db_session, embedder)
        assert count == 2

    def test_links_defect_to_requirement(self, req_csv, defect_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        ingest_defects(parse_defects_csv(defect_csv), db_session, embedder)

        req = db_session.get(Requirement, "REQ-001")
        assert len(req.defects) == 1
        assert req.defects[0].id == "JIRA-001"

    def test_multi_link_defect(self, req_csv, defect_csv, db_session, embedder):
        """JIRA-002 links to both REQ-002 and TSR-001."""
        self._seed_reqs(req_csv, db_session, embedder)
        ingest_defects(parse_defects_csv(defect_csv), db_session, embedder)

        defect = db_session.get(Defect, "JIRA-002")
        linked_ids = {r.id for r in defect.requirements}
        assert linked_ids == {"REQ-002", "TSR-001"}

    def test_upsert_does_not_duplicate(self, req_csv, defect_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        records = parse_defects_csv(defect_csv)
        ingest_defects(records, db_session, embedder)
        second_count = ingest_defects(records, db_session, embedder)
        assert second_count == 0
        assert db_session.query(Defect).count() == 2


# ── Cross-model relationship tests ───────────────────────────────────────────

class TestFullIngestionPipeline:
    def test_full_pipeline_counts(self, req_csv, tc_csv, defect_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        ingest_defects(parse_defects_csv(defect_csv), db_session, embedder)

        assert db_session.query(Requirement).count() == 4
        assert db_session.query(TestCase).count() == 3
        assert db_session.query(Defect).count() == 2

    def test_requirement_with_both_tests_and_defects(
        self, req_csv, tc_csv, defect_csv, db_session, embedder
    ):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        ingest_defects(parse_defects_csv(defect_csv), db_session, embedder)

        req = db_session.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 1
        assert len(req.defects) == 1

    def test_safety_chain_integrity(self, req_csv, db_session, embedder):
        """SG-001 → TSR-001 parent_id chain must be stored correctly."""
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)

        sg = db_session.get(Requirement, "SG-001")
        tsr = db_session.get(Requirement, "TSR-001")
        assert tsr.parent_id == sg.id
        assert tsr in sg.children
