"""
JSON REST API — programmatic access to the knowledge base and validation engine.

All endpoints are mounted at /api/* by the app factory.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...kb_ingestor.embedder import KBEmbedder
from ...kb_ingestor.ingest import ingest_file
from ...kb_ingestor.models import Defect, Requirement, TestCase
from ...validation_engine.validator import ValidationEngine
from ..deps import get_db, get_embedder

router = APIRouter()


# ── Response schemas ──────────────────────────────────────────────────────────

class RequirementSummary(BaseModel):
    id: str
    title: str
    asil_level: str
    req_type: str
    coverage_status: str
    parent_id: Optional[str] = None


class RequirementDetail(RequirementSummary):
    text: str
    status: str
    asil_decomposition: bool
    decomposition_partner_id: Optional[str] = None
    linked_test_count: int
    linked_defect_count: int
    child_count: int


# ── Requirements ──────────────────────────────────────────────────────────────

@router.get("/requirements", response_model=List[RequirementSummary])
async def list_requirements(
    asil: Optional[str] = None,
    coverage: Optional[str] = None,
    req_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(Requirement)
    if asil:
        stmt = stmt.where(Requirement.asil_level == asil)
    if coverage:
        stmt = stmt.where(Requirement.coverage_status == coverage)
    if req_type:
        stmt = stmt.where(Requirement.req_type == req_type)
    reqs = db.scalars(stmt.order_by(Requirement.id)).all()
    return [
        RequirementSummary(
            id=r.id,
            title=r.title or "",
            asil_level=r.asil_level,
            req_type=r.req_type,
            coverage_status=r.coverage_status,
            parent_id=r.parent_id,
        )
        for r in reqs
    ]


@router.get("/requirements/{req_id}", response_model=RequirementDetail)
async def get_requirement(req_id: str, db: Session = Depends(get_db)):
    req = db.get(Requirement, req_id)
    if req is None:
        raise HTTPException(status_code=404, detail=f"Requirement {req_id!r} not found")
    return RequirementDetail(
        id=req.id,
        title=req.title or "",
        asil_level=req.asil_level,
        req_type=req.req_type,
        coverage_status=req.coverage_status,
        parent_id=req.parent_id,
        text=req.text,
        status=req.status,
        asil_decomposition=req.asil_decomposition,
        decomposition_partner_id=req.decomposition_partner_id,
        linked_test_count=len(req.test_cases),
        linked_defect_count=len(req.defects),
        child_count=len(req.children),
    )


# ── Validation ────────────────────────────────────────────────────────────────

@router.post("/validate/{req_id}")
async def validate_requirement(
    req_id: str,
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    if db.get(Requirement, req_id) is None:
        raise HTTPException(status_code=404, detail=f"Requirement {req_id!r} not found")
    engine = ValidationEngine(session=db, embedder=embedder)
    try:
        result = await asyncio.to_thread(engine.validate_requirement, req_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return result.to_dict()


@router.post("/validate")
async def validate_all(
    asil_filter: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    engine = ValidationEngine(session=db, embedder=embedder)
    results = await asyncio.to_thread(engine.validate_all, asil_filter)
    return {
        "total": len(results),
        "verdicts": {
            "Pass": sum(1 for r in results if r.overall_verdict == "Pass"),
            "Warning": sum(1 for r in results if r.overall_verdict == "Warning"),
            "Fail": sum(1 for r in results if r.overall_verdict == "Fail"),
        },
        "results": [r.to_dict() for r in results],
    }


# ── Ingest ────────────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    artifact_type: Optional[str] = None,
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    suffix = Path(file.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        await asyncio.to_thread(ingest_file, tmp_path, artifact_type, db, embedder)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return {"status": "ok", "file": file.filename}


# ── Health ────────────────────────────────────────────────────────────────────

@router.get("/health")
async def health(
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    req_count = db.scalar(select(func.count()).select_from(Requirement))
    tc_count = db.scalar(select(func.count()).select_from(TestCase))
    def_count = db.scalar(select(func.count()).select_from(Defect))
    return {
        "status": "ok",
        "sqlite": {
            "requirements": req_count,
            "test_cases": tc_count,
            "defects": def_count,
        },
        "chromadb": embedder.counts(),
    }
