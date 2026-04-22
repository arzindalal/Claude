"""
Tests for the Phase 3 FastAPI layer.

Strategy
--------
- `get_db` and `get_embedder` are overridden via dependency_overrides so tests
  never hit the real ChromaDB or require sentence-transformers to load.
- ValidationEngine is patched at the module level for validation route tests.
- `TestClient` triggers FastAPI's lifespan; KBEmbedder is patched so the
  lifespan startup does not attempt to load the sentence-transformer model.
"""

from __future__ import annotations

import json
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from iso26262_validator.api.app import app
from iso26262_validator.api.deps import get_db, get_embedder
from iso26262_validator.kb_ingestor.database import get_engine, get_session
from iso26262_validator.kb_ingestor.models import Base, Defect, Requirement, TestCase
from iso26262_validator.validation_engine.result_models import (
    DefectRiskResult,
    QualityResult,
    SafetyChainResult,
    TraceabilityResult,
    ValidationResult,
)


# ── Test fixtures ─────────────────────────────────────────────────────────────

class _StubEmbedder:
    def query_similar_tests(self, *a, **kw):
        return []

    def query_related_defects(self, *a, **kw):
        return []

    def counts(self):
        return {"requirements": 0, "test_cases": 0, "defects": 0}


def _make_result(req_id: str = "REQ-001") -> ValidationResult:
    return ValidationResult(
        requirement_id=req_id,
        traceability=TraceabilityResult(
            covered=True,
            linked_test_ids=["TC-001"],
            missing_levels=[],
            verdict_summary="1 Pass",
            notes="",
        ),
        defect_risk=DefectRiskResult(
            risk_level="Low",
            open_defect_count=0,
            critical_defect_ids=[],
            assessment="No open defects.",
        ),
        quality=QualityResult(score=80, issues=[], suggestions=[]),
        safety_chain=SafetyChainResult(
            chain_complete=True,
            asil_level="B",
            parent_id=None,
            children_ids=[],
            gaps=[],
            decomposition_valid=True,
        ),
        overall_verdict="Pass",
        coverage_status="Covered",
        raw_response='{"overall_verdict":"Pass"}',
        model_used="claude-sonnet-4-6",
        timestamp="2025-01-01T00:00:00+00:00",
    )


@pytest.fixture
def test_db(tmp_path):
    engine = get_engine(str(tmp_path / "test_api.sqlite"))
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def client(test_db):
    stub_emb = _StubEmbedder()

    def override_db() -> Generator[Session, None, None]:
        s = get_session(test_db)
        try:
            yield s
        finally:
            s.close()

    def override_embedder():
        return stub_emb

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_embedder] = override_embedder

    # Prevent KBEmbedder from loading sentence-transformers during lifespan
    with patch("iso26262_validator.api.app.KBEmbedder"):
        with TestClient(app) as c:
            yield c

    app.dependency_overrides.clear()


@pytest.fixture
def req_in_db(test_db):
    s = get_session(test_db)
    req = Requirement(
        id="REQ-001",
        text="The ECU shall monitor APS voltage within 0.5V–4.5V.",
        title="APS Voltage Monitor",
        asil_level="B",
        req_type="Functional",
    )
    s.add(req)
    s.commit()
    s.close()
    return req


# ── /api/health ───────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "sqlite" in body
        assert "chromadb" in body

    def test_empty_db_counts(self, client):
        resp = client.get("/api/health")
        body = resp.json()
        assert body["sqlite"]["requirements"] == 0


# ── /api/requirements ─────────────────────────────────────────────────────────

class TestListRequirements:
    def test_empty_db(self, client):
        resp = client.get("/api/requirements")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_added_requirement(self, client, req_in_db):
        resp = client.get("/api/requirements")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "REQ-001"
        assert data[0]["asil_level"] == "B"

    def test_filter_by_asil(self, client, test_db):
        s = get_session(test_db)
        s.add(Requirement(id="R-B", text="B req", title="B", asil_level="B"))
        s.add(Requirement(id="R-D", text="D req", title="D", asil_level="D"))
        s.commit()
        s.close()

        resp = client.get("/api/requirements?asil=D")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == "R-D"

    def test_filter_by_coverage(self, client, test_db):
        s = get_session(test_db)
        s.add(Requirement(id="R-COV", text="t", title="t", asil_level="B", coverage_status="Covered"))
        s.add(Requirement(id="R-PND", text="t", title="t", asil_level="B", coverage_status="Pending"))
        s.commit()
        s.close()

        resp = client.get("/api/requirements?coverage=Covered")
        data = resp.json()
        assert all(r["coverage_status"] == "Covered" for r in data)

    def test_filter_by_req_type(self, client, test_db):
        s = get_session(test_db)
        s.add(Requirement(id="R-TSR", text="t", title="t", asil_level="C", req_type="TSR"))
        s.add(Requirement(id="R-SSR", text="t", title="t", asil_level="B", req_type="SSR"))
        s.commit()
        s.close()

        resp = client.get("/api/requirements?req_type=TSR")
        data = resp.json()
        assert all(r["req_type"] == "TSR" for r in data)


class TestGetRequirement:
    def test_found(self, client, req_in_db):
        resp = client.get("/api/requirements/REQ-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "REQ-001"
        assert "text" in data
        assert "linked_test_count" in data

    def test_not_found(self, client):
        resp = client.get("/api/requirements/NONEXISTENT")
        assert resp.status_code == 404

    def test_counts_linked_tests(self, client, test_db):
        s = get_session(test_db)
        req = Requirement(id="R-TC", text="t", title="t", asil_level="B")
        tc = TestCase(id="TC-X", title="Test", level="SW Unit Testing",
                      lifecycle_state="Draft", verdict="Not Run")
        req.test_cases.append(tc)
        s.add(req)
        s.commit()
        s.close()

        resp = client.get("/api/requirements/R-TC")
        assert resp.json()["linked_test_count"] == 1


# ── /api/validate ─────────────────────────────────────────────────────────────

class TestValidateRequirement:
    def test_validates_existing_req(self, client, req_in_db):
        with patch(
            "iso26262_validator.api.routers.rest.ValidationEngine"
        ) as MockEngine:
            instance = MockEngine.return_value
            instance.validate_requirement.return_value = _make_result("REQ-001")

            resp = client.post("/api/validate/REQ-001")

        assert resp.status_code == 200
        body = resp.json()
        assert body["overall_verdict"] == "Pass"
        assert body["coverage_status"] == "Covered"

    def test_404_for_missing_req(self, client):
        resp = client.post("/api/validate/GHOST-001")
        assert resp.status_code == 404

    def test_500_on_engine_error(self, client, req_in_db):
        with patch(
            "iso26262_validator.api.routers.rest.ValidationEngine"
        ) as MockEngine:
            instance = MockEngine.return_value
            instance.validate_requirement.side_effect = RuntimeError("API down")

            resp = client.post("/api/validate/REQ-001")

        assert resp.status_code == 500


class TestValidateAll:
    def test_returns_summary(self, client, test_db):
        s = get_session(test_db)
        s.add(Requirement(id="R-VA1", text="t", title="t", asil_level="B"))
        s.add(Requirement(id="R-VA2", text="t", title="t", asil_level="D"))
        s.commit()
        s.close()

        with patch(
            "iso26262_validator.api.routers.rest.ValidationEngine"
        ) as MockEngine:
            instance = MockEngine.return_value
            instance.validate_all.return_value = [
                _make_result("R-VA1"), _make_result("R-VA2")
            ]

            resp = client.post("/api/validate")

        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert body["verdicts"]["Pass"] == 2


# ── /api/ingest ───────────────────────────────────────────────────────────────

class TestIngestAPI:
    def test_ingest_csv(self, client, tmp_path):
        csv_content = (
            "id,title,text,asil_level,req_type,status\n"
            "REQ-ING,Ingest Test,The system shall respond.,B,Functional,Active\n"
        )
        csv_file = tmp_path / "req.csv"
        csv_file.write_text(csv_content)

        with patch("iso26262_validator.api.routers.rest.ingest_file"):
            resp = client.post(
                "/api/ingest",
                files={"file": ("req.csv", csv_file.read_bytes(), "text/csv")},
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ingest_bad_file_returns_422(self, client):
        with patch(
            "iso26262_validator.api.routers.rest.ingest_file",
            side_effect=ValueError("unknown format"),
        ):
            resp = client.post(
                "/api/ingest",
                files={"file": ("bad.csv", b"not,valid,csv\n", "text/csv")},
            )

        assert resp.status_code == 422


# ── HTML UI routes ────────────────────────────────────────────────────────────

class TestUIRoutes:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
        assert "ISO 26262" in resp.text

    def test_index_shows_requirements(self, client, req_in_db):
        resp = client.get("/")
        assert "REQ-001" in resp.text
        assert "APS Voltage Monitor" in resp.text

    def test_partials_requirements_returns_rows(self, client, req_in_db):
        resp = client.get(
            "/partials/requirements",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "REQ-001" in resp.text

    def test_partials_req_detail_found(self, client, req_in_db):
        resp = client.get(
            "/partials/requirements/REQ-001",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "APS Voltage Monitor" in resp.text
        assert "Validate with Claude" in resp.text

    def test_partials_req_detail_not_found(self, client):
        resp = client.get("/partials/requirements/GHOST")
        assert resp.status_code == 404

    def test_partials_validate_returns_result_html(self, client, req_in_db):
        with patch(
            "iso26262_validator.api.routers.ui.ValidationEngine"
        ) as MockEngine:
            instance = MockEngine.return_value
            instance.validate_requirement.return_value = _make_result("REQ-001")

            resp = client.post(
                "/partials/validate/REQ-001",
                headers={"HX-Request": "true"},
            )

        assert resp.status_code == 200
        assert "Pass" in resp.text

    def test_partials_validate_error_returns_html_error(self, client, req_in_db):
        with patch(
            "iso26262_validator.api.routers.ui.ValidationEngine"
        ) as MockEngine:
            instance = MockEngine.return_value
            instance.validate_requirement.side_effect = ValueError("not found")

            resp = client.post("/partials/validate/REQ-001")

        assert resp.status_code == 422
        assert "failed" in resp.text.lower()

    def test_index_filter_by_asil(self, client, test_db):
        s = get_session(test_db)
        s.add(Requirement(id="R-B-UI", text="t", title="B req", asil_level="B"))
        s.add(Requirement(id="R-D-UI", text="t", title="D req", asil_level="D"))
        s.commit()
        s.close()

        resp = client.get("/?asil=D")
        assert "R-D-UI" in resp.text
        assert "R-B-UI" not in resp.text
