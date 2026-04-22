"""
Tests for Phase 4 — Export layer.

Coverage
--------
- ReportGenerator.generate_requirements_csv: correct columns, data rows, filtering
- ReportGenerator.generate_excel: returns valid xlsx bytes, correct sheet names,
  header rows, data rows for each sheet
- GET /api/export/excel: correct content-type and attachment header
- GET /api/export/csv: correct content-type, attachment header, and content
"""

from __future__ import annotations

import csv
import io
from typing import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iso26262_validator.api.app import app
from iso26262_validator.api.deps import get_db, get_embedder
from iso26262_validator.export.report import ReportGenerator
from iso26262_validator.kb_ingestor.database import get_engine, get_session
from iso26262_validator.kb_ingestor.models import Base, Defect, Requirement, TestCase


# ── Fixtures ──────────────────────────────────────────────────────────────────

class _StubEmbedder:
    def query_similar_tests(self, *a, **kw):
        return []

    def query_related_defects(self, *a, **kw):
        return []

    def counts(self):
        return {"requirements": 0, "test_cases": 0, "defects": 0}


@pytest.fixture
def test_db(tmp_path):
    engine = get_engine(str(tmp_path / "test_export.sqlite"))
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def populated_db(test_db):
    """DB with one requirement, one test case, and one defect all linked together."""
    s = get_session(test_db)

    req = Requirement(
        id="REQ-EX1",
        text="The system shall brake within 100ms.",
        title="Emergency Brake Response",
        asil_level="D",
        req_type="Functional",
        coverage_status="Covered",
        status="Active",
    )
    req2 = Requirement(
        id="REQ-EX2",
        text="The system shall log all events.",
        title="Event Logging",
        asil_level="B",
        req_type="Non-Functional",
        coverage_status="Pending",
        status="Active",
        parent_id="REQ-EX1",
    )
    tc = TestCase(
        id="TC-EX1",
        title="Brake Timing Test",
        level="SW Unit Testing",
        lifecycle_state="Executed",
        verdict="Pass",
        verification_method="Dynamic Test",
    )
    defect = Defect(
        id="DEF-EX1",
        summary="Brake latency exceeds spec under load.",
        severity="High",
        status="Open",
    )
    req.test_cases.append(tc)
    req.defects.append(defect)

    s.add_all([req, req2, tc, defect])
    s.commit()
    s.close()
    return test_db


@pytest.fixture
def db_session(populated_db) -> Session:
    s = get_session(populated_db)
    yield s
    s.close()


@pytest.fixture
def client(populated_db):
    stub_emb = _StubEmbedder()

    def override_db() -> Generator[Session, None, None]:
        s = get_session(populated_db)
        try:
            yield s
        finally:
            s.close()

    def override_embedder():
        return stub_emb

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_embedder] = override_embedder

    with patch("iso26262_validator.api.app.KBEmbedder"):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


# ── CSV tests ─────────────────────────────────────────────────────────────────

class TestGenerateCSV:
    def test_returns_string(self, db_session):
        gen = ReportGenerator(session=db_session)
        result = gen.generate_requirements_csv()
        assert isinstance(result, str)

    def test_has_header_row(self, db_session):
        gen = ReportGenerator(session=db_session)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        header = next(reader)
        assert "ID" in header
        assert "Title" in header
        assert "ASIL" in header
        assert "Coverage Status" in header

    def test_contains_requirement_data(self, db_session):
        gen = ReportGenerator(session=db_session)
        csv_str = gen.generate_requirements_csv()
        assert "REQ-EX1" in csv_str
        assert "Emergency Brake Response" in csv_str
        assert "REQ-EX2" in csv_str

    def test_correct_row_count(self, db_session):
        gen = ReportGenerator(session=db_session)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        rows = list(reader)
        # header + 2 requirements
        assert len(rows) == 3

    def test_pass_count_column(self, db_session):
        gen = ReportGenerator(session=db_session)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        header = next(reader)
        pass_col = header.index("Pass Count")
        # REQ-EX1 has 1 passing TC
        req_ex1_row = next(r for r in reader if r[0] == "REQ-EX1")
        assert req_ex1_row[pass_col] == "1"

    def test_open_defect_count_column(self, db_session):
        gen = ReportGenerator(session=db_session)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        header = next(reader)
        defect_col = header.index("Open Defect Count")
        rows = {r[0]: r for r in reader}
        assert rows["REQ-EX1"][defect_col] == "1"
        assert rows["REQ-EX2"][defect_col] == "0"

    def test_parent_id_column(self, db_session):
        gen = ReportGenerator(session=db_session)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        header = next(reader)
        parent_col = header.index("Parent ID")
        rows = {r[0]: r for r in reader}
        assert rows["REQ-EX2"][parent_col] == "REQ-EX1"
        assert rows["REQ-EX1"][parent_col] == ""

    def test_empty_db_returns_header_only(self, test_db):
        s = get_session(test_db)
        gen = ReportGenerator(session=s)
        reader = csv.reader(io.StringIO(gen.generate_requirements_csv()))
        rows = list(reader)
        s.close()
        assert len(rows) == 1  # header only


# ── Excel tests ───────────────────────────────────────────────────────────────

class TestGenerateExcel:
    def test_returns_bytes(self, db_session):
        gen = ReportGenerator(session=db_session)
        result = gen.generate_excel()
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_valid_xlsx_magic_bytes(self, db_session):
        gen = ReportGenerator(session=db_session)
        result = gen.generate_excel()
        # XLSX is a ZIP file — starts with PK
        assert result[:2] == b"PK"

    def test_has_all_five_sheets(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        assert set(wb.sheetnames) == {
            "Summary", "Requirements", "Traceability Matrix",
            "Test Cases", "Defects",
        }

    def test_requirements_sheet_has_header(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Requirements"]
        header = [ws.cell(1, c).value for c in range(1, 13)]
        assert "ID" in header
        assert "ASIL" in header
        assert "Coverage Status" in header

    def test_requirements_sheet_has_data_rows(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Requirements"]
        # Row 1 = header, rows 2+ = data
        assert ws.max_row >= 3  # header + 2 reqs

    def test_requirements_sheet_req_id_present(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Requirements"]
        ids = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
        assert "REQ-EX1" in ids

    def test_traceability_matrix_columns_include_levels(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Traceability Matrix"]
        header = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        assert "SW Unit Testing" in header

    def test_traceability_pass_cell_for_covered_req(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Traceability Matrix"]
        header = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        sw_unit_col = header.index("SW Unit Testing") + 1
        # REQ-EX1 is row 2
        cell_val = ws.cell(2, sw_unit_col).value
        assert cell_val == "1P / 0F"

    def test_test_cases_sheet_has_header(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Test Cases"]
        header = [ws.cell(1, c).value for c in range(1, 8)]
        assert "ID" in header
        assert "Verdict" in header

    def test_test_cases_sheet_data(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Test Cases"]
        ids = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
        assert "TC-EX1" in ids

    def test_defects_sheet_has_data(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Defects"]
        ids = [ws.cell(r, 1).value for r in range(2, ws.max_row + 1)]
        assert "DEF-EX1" in ids

    def test_defects_linked_req_ids(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Defects"]
        # Column 5 = Linked Requirement IDs
        linked = ws.cell(2, 5).value
        assert "REQ-EX1" in (linked or "")

    def test_summary_sheet_contains_total(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Summary"]
        all_values = [str(ws.cell(r, 1).value or "") for r in range(1, ws.max_row + 1)]
        assert any("Total Requirements" in v for v in all_values)

    def test_empty_db_still_produces_valid_workbook(self, test_db):
        import openpyxl
        s = get_session(test_db)
        gen = ReportGenerator(session=s)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        s.close()
        assert "Requirements" in wb.sheetnames

    def test_frozen_panes_on_requirements_sheet(self, db_session):
        import openpyxl
        gen = ReportGenerator(session=db_session)
        wb = openpyxl.load_workbook(io.BytesIO(gen.generate_excel()))
        ws = wb["Requirements"]
        assert ws.freeze_panes == "A2"


# ── HTTP endpoint tests ───────────────────────────────────────────────────────

class TestExportEndpoints:
    def test_excel_endpoint_status(self, client):
        resp = client.get("/api/export/excel")
        assert resp.status_code == 200

    def test_excel_content_type(self, client):
        resp = client.get("/api/export/excel")
        assert "spreadsheetml" in resp.headers["content-type"]

    def test_excel_content_disposition(self, client):
        resp = client.get("/api/export/excel")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".xlsx" in cd

    def test_excel_body_is_valid_xlsx(self, client):
        import openpyxl
        resp = client.get("/api/export/excel")
        wb = openpyxl.load_workbook(io.BytesIO(resp.content))
        assert "Requirements" in wb.sheetnames

    def test_csv_endpoint_status(self, client):
        resp = client.get("/api/export/csv")
        assert resp.status_code == 200

    def test_csv_content_type(self, client):
        resp = client.get("/api/export/csv")
        assert "text/csv" in resp.headers["content-type"]

    def test_csv_content_disposition(self, client):
        resp = client.get("/api/export/csv")
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert ".csv" in cd

    def test_csv_body_contains_req_id(self, client):
        resp = client.get("/api/export/csv")
        assert "REQ-EX1" in resp.text

    def test_csv_body_has_header(self, client):
        resp = client.get("/api/export/csv")
        first_line = resp.text.splitlines()[0]
        assert "ID" in first_line
        assert "ASIL" in first_line
