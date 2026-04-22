"""
Tests for Phase 1: knowledge-base ingestion.

Covers:
  - CSV parsers (happy path, alternate column names, missing mandatory columns)
  - SQLite upsert logic (new vs. update, no-duplicate guarantee)
  - Relationship wiring (Requirement ↔ TestCase, Requirement ↔ Defect)
  - Link reconciliation on update (stale links removed, new links added)
  - Cross-session duplicate-link prevention (DB-level check)
  - Atomic flush/embed/commit rollback on embedder failure
  - Schema fields: lifecycle_state, verdict, verification_method, asil_decomposition
  - Defect alias disambiguation (summary vs. description column)
  - Embedder mock to isolate DB logic from heavy ML dependencies
"""

from __future__ import annotations

import csv
from typing import Optional

import pytest

from kb_ingestor.database import get_engine, get_session
from kb_ingestor.ingest import ingest_defects, ingest_requirements, ingest_test_cases
from kb_ingestor.models import Defect, Requirement, TestCase
from kb_ingestor.parsers.csv_parser import (
    parse_defects_csv,
    parse_requirements_csv,
    parse_test_cases_csv,
    detect_artifact_type,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _NullEmbedder:
    """Stand-in embedder that discards all data — avoids downloading ML models."""
    def add_requirements(self, _): pass
    def add_test_cases(self, _): pass
    def add_defects(self, _): pass
    def counts(self): return {"requirements": 0, "test_cases": 0, "defects": 0}


class _FailingEmbedder:
    """Embedder that always raises — used to test atomic rollback."""
    def add_requirements(self, _): raise RuntimeError("ChromaDB unavailable")
    def add_test_cases(self, _): raise RuntimeError("ChromaDB unavailable")
    def add_defects(self, _): raise RuntimeError("ChromaDB unavailable")


@pytest.fixture
def embedder():
    return _NullEmbedder()


@pytest.fixture
def db_session(tmp_path):
    engine = get_engine(str(tmp_path / "test.sqlite"))
    session = get_session(engine)
    yield session
    session.close()


def _fresh_session(tmp_path, db_name: str = "test.sqlite"):
    """Open a brand-new session to the same DB file — simulates a CLI re-run."""
    engine = get_engine(str(tmp_path / db_name))
    return get_session(engine)


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
        w.writerow(["id", "title", "steps", "expected_result", "level", "lifecycle_state", "verdict", "linked_req_ids"])
        w.writerow(["TC-001", "Verify 50ms response", "1. Apply input\n2. Measure", "Response ≤ 50ms", "SW Qualification Testing", "Draft", "Not Run", "REQ-001"])
        w.writerow(["TC-002", "Verify safe state on fault", "1. Inject fault\n2. Observe", "Safe state within 20ms", "SW Qualification Testing", "Draft", "Not Run", "REQ-002"])
        w.writerow(["TC-003", "Verify APS monitoring rate", "1. Sample APS\n2. Check interval", "Interval ≤ 10ms", "SW Qualification Testing", "Executed", "Pass", "TSR-001"])
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
            fp.write("title,asil_level\nFoo,B\n")
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

    def test_header_only_csv_returns_empty(self, tmp_path):
        f = tmp_path / "header_only.csv"
        with open(f, "w", newline="") as fp:
            fp.write("id,text,asil_level\n")
        records = parse_requirements_csv(str(f))
        assert records == []


class TestTestCasesCSVParser:
    def test_parses_all_rows(self, tc_csv):
        records = parse_test_cases_csv(tc_csv)
        assert len(records) == 3

    def test_linked_req_ids_parsed(self, tc_csv):
        records = parse_test_cases_csv(tc_csv)
        assert records[0]["linked_req_ids"] == ["REQ-001"]

    def test_lifecycle_state_and_verdict_explicit(self, tc_csv):
        records = parse_test_cases_csv(tc_csv)
        assert records[2]["lifecycle_state"] == "Executed"
        assert records[2]["verdict"] == "Pass"

    def test_legacy_status_open_maps_to_draft_not_run(self, tmp_path):
        f = tmp_path / "tc_legacy.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "title", "status"])
            w.writerow(["TC-L1", "Legacy open test", "Open"])
        records = parse_test_cases_csv(str(f))
        assert records[0]["lifecycle_state"] == "Draft"
        assert records[0]["verdict"] == "Not Run"

    def test_legacy_status_pass_maps_to_executed_pass(self, tmp_path):
        f = tmp_path / "tc_legacy_pass.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "title", "status"])
            w.writerow(["TC-L2", "Legacy passed test", "Pass"])
        records = parse_test_cases_csv(str(f))
        assert records[0]["lifecycle_state"] == "Executed"
        assert records[0]["verdict"] == "Pass"

    def test_multi_link_ids_parsed(self, tmp_path):
        """Comma, semicolon, and pipe separators must all be handled."""
        f = tmp_path / "tc.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "title", "linked_req_ids"])
            w.writerow(["TC-X", "Multi-link test", "REQ-001;REQ-002|REQ-003"])
        records = parse_test_cases_csv(str(f))
        assert records[0]["linked_req_ids"] == ["REQ-001", "REQ-002", "REQ-003"]

    def test_level_normalised_to_iso26262(self, tmp_path):
        f = tmp_path / "tc_level.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "title", "level"])
            w.writerow(["TC-N1", "Unit test", "Unit"])
            w.writerow(["TC-N2", "System test", "System"])
        records = parse_test_cases_csv(str(f))
        assert records[0]["level"] == "SW Unit Testing"
        assert records[1]["level"] == "SW Qualification Testing"

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

    def test_description_column_not_consumed_by_summary(self, tmp_path):
        """A CSV with only a 'description' column must route it to description, not summary."""
        f = tmp_path / "jira.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "summary", "description", "severity"])
            w.writerow(["J-001", "Short title", "Long detailed description here", "High"])
        records = parse_defects_csv(str(f))
        assert records[0]["summary"] == "Short title"
        assert records[0]["description"] == "Long detailed description here"

    def test_single_description_column_goes_to_description_not_summary(self, tmp_path):
        """Without a 'summary' column, description must NOT silently win the summary slot."""
        f = tmp_path / "jira_no_summary.csv"
        with open(f, "w", newline="") as fp:
            w = csv.writer(fp)
            w.writerow(["id", "description", "severity"])
            w.writerow(["J-002", "Full description text", "Medium"])
        # 'summary' column is absent → should raise ValueError
        with pytest.raises(ValueError, match="missing required columns"):
            parse_defects_csv(str(f))


class TestDetectArtifactType:
    def test_detects_test_cases(self):
        assert detect_artifact_type({"id", "title", "steps", "expected_result"}) == "test_cases"

    def test_detects_defects(self):
        assert detect_artifact_type({"id", "summary", "severity", "status"}) == "defects"

    def test_falls_back_to_requirements(self):
        assert detect_artifact_type({"id", "text", "asil_level"}) == "requirements"


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
        updated = [dict(r) for r in records]
        updated[0]["status"] = "Deprecated"
        ingest_requirements(updated, db_session, embedder)
        assert db_session.get(Requirement, "REQ-001").status == "Deprecated"

    def test_coverage_status_not_clobbered_on_upsert(self, req_csv, db_session, embedder):
        """coverage_status set by Phase 2 must survive a re-ingest."""
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        req = db_session.get(Requirement, "REQ-001")
        req.coverage_status = "Covered"
        db_session.commit()

        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        assert db_session.get(Requirement, "REQ-001").coverage_status == "Covered"

    def test_embedder_failure_rolls_back_sqlite(self, req_csv, db_session):
        """If ChromaDB upsert raises, SQLite must not persist the new rows."""
        records = parse_requirements_csv(req_csv)
        with pytest.raises(RuntimeError, match="ChromaDB unavailable"):
            ingest_requirements(records, db_session, _FailingEmbedder())
        assert db_session.query(Requirement).count() == 0


class TestTestCaseIngestion:
    def _seed_reqs(self, req_csv, session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), session, embedder)

    def test_inserts_new_records(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        count = ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        assert count == 3

    def test_lifecycle_state_and_verdict_stored(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        tc = db_session.get(TestCase, "TC-003")
        assert tc.lifecycle_state == "Executed"
        assert tc.verdict == "Pass"

    def test_links_requirement_to_test_case(self, req_csv, tc_csv, db_session, embedder):
        self._seed_reqs(req_csv, db_session, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        req = db_session.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 1
        assert req.test_cases[0].id == "TC-001"

    def test_cross_session_no_duplicate_links(self, req_csv, tc_csv, tmp_path, embedder):
        """Re-ingesting with a fresh session must not create duplicate links in req_test_link."""
        db_path = str(tmp_path / "cross_session.sqlite")
        # First session
        s1 = get_session(get_engine(db_path))
        ingest_requirements(parse_requirements_csv(req_csv), s1, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), s1, embedder)
        s1.close()

        # Second session — simulates a CLI re-run
        s2 = get_session(get_engine(db_path))
        ingest_test_cases(parse_test_cases_csv(tc_csv), s2, embedder)
        req = s2.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 1
        s2.close()

    def test_stale_link_removed_on_update(self, req_csv, tc_csv, tmp_path, embedder):
        """Re-ingesting a test case with fewer linked reqs must remove the dropped link."""
        db_path = str(tmp_path / "stale_link.sqlite")
        s1 = get_session(get_engine(db_path))
        ingest_requirements(parse_requirements_csv(req_csv), s1, embedder)
        ingest_test_cases(parse_test_cases_csv(tc_csv), s1, embedder)

        # Verify TC-001 links REQ-001
        assert len(s1.get(Requirement, "REQ-001").test_cases) == 1
        s1.close()

        # Re-ingest TC-001 with the link to REQ-001 removed
        s2 = get_session(get_engine(db_path))
        updated_records = [{"id": "TC-001", "title": "Verify 50ms response", "linked_req_ids": []}]
        # Add missing required fields with defaults
        for r in updated_records:
            r.setdefault("steps", "")
            r.setdefault("expected_result", "")
            r.setdefault("level", "SW Qualification Testing")
            r.setdefault("verification_method", "Dynamic Test")
            r.setdefault("lifecycle_state", "Draft")
            r.setdefault("verdict", "Not Run")
            r.setdefault("source_file", "")
            r.setdefault("objective", "")
            r.setdefault("preconditions", "")
        ingest_test_cases(updated_records, s2, embedder)

        req = s2.get(Requirement, "REQ-001")
        assert len(req.test_cases) == 0
        s2.close()

    def test_unresolved_req_link_is_silently_skipped(self, tc_csv, db_session, embedder):
        """Test cases with links to non-existent requirements must not crash."""
        ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, embedder)
        assert db_session.query(TestCase).count() == 3

    def test_embedder_failure_rolls_back_sqlite(self, req_csv, tc_csv, db_session):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, _NullEmbedder())
        with pytest.raises(RuntimeError, match="ChromaDB unavailable"):
            ingest_test_cases(parse_test_cases_csv(tc_csv), db_session, _FailingEmbedder())
        assert db_session.query(TestCase).count() == 0


class TestDefectIngestion:
    def _seed_reqs(self, req_csv, session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), session, embedder)

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
        assert {r.id for r in defect.requirements} == {"REQ-002", "TSR-001"}

    def test_cross_session_no_duplicate_links(self, req_csv, defect_csv, tmp_path, embedder):
        db_path = str(tmp_path / "defect_cross.sqlite")
        s1 = get_session(get_engine(db_path))
        ingest_requirements(parse_requirements_csv(req_csv), s1, embedder)
        ingest_defects(parse_defects_csv(defect_csv), s1, embedder)
        s1.close()

        s2 = get_session(get_engine(db_path))
        ingest_defects(parse_defects_csv(defect_csv), s2, embedder)
        req = s2.get(Requirement, "REQ-001")
        assert len(req.defects) == 1
        s2.close()

    def test_stale_defect_link_removed_on_update(self, req_csv, defect_csv, tmp_path, embedder):
        db_path = str(tmp_path / "defect_stale.sqlite")
        s1 = get_session(get_engine(db_path))
        ingest_requirements(parse_requirements_csv(req_csv), s1, embedder)
        ingest_defects(parse_defects_csv(defect_csv), s1, embedder)
        s1.close()

        s2 = get_session(get_engine(db_path))
        updated = [{"id": "JIRA-001", "summary": "Response time 62ms on cold start",
                    "description": "", "severity": "High", "status": "Open",
                    "linked_req_ids": [], "source_file": ""}]
        ingest_defects(updated, s2, embedder)
        assert len(s2.get(Requirement, "REQ-001").defects) == 0
        s2.close()

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
        """SG-001 → TSR-001 parent_id chain must be stored and traversable."""
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        sg = db_session.get(Requirement, "SG-001")
        tsr = db_session.get(Requirement, "TSR-001")
        assert tsr.parent_id == sg.id
        assert tsr in sg.children
        assert tsr.parent is sg

    def test_asil_decomposition_fields_default(self, req_csv, db_session, embedder):
        ingest_requirements(parse_requirements_csv(req_csv), db_session, embedder)
        req = db_session.get(Requirement, "REQ-001")
        assert req.asil_decomposition is False
        assert req.decomposition_partner_id is None
