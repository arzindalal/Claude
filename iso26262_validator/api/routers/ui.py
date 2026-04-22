"""
HTML routes for the HTMX-driven UI.

Full-page routes:
  GET /            — requirements list page

HTMX partial routes (return HTML fragments):
  GET  /partials/requirements         — filtered <tbody> rows
  GET  /partials/requirements/{id}    — requirement detail panel
  POST /partials/validate/{id}        — run validation, return result cards

Form submission:
  POST /ingest                        — upload CSV/Excel, redirect to /
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...kb_ingestor.embedder import KBEmbedder
from ...kb_ingestor.ingest import ingest_file
from ...kb_ingestor.models import ASILLevel, CoverageStatus, Requirement, RequirementType
from ...validation_engine.validator import ValidationEngine
from ..deps import get_db, get_embedder
from ..templates import templates

router = APIRouter()


# ── Filter helpers ────────────────────────────────────────────────────────────

def _apply_filters(
    stmt,
    asil: Optional[str],
    coverage: Optional[str],
    req_type: Optional[str],
):
    if asil:
        stmt = stmt.where(Requirement.asil_level == asil)
    if coverage:
        stmt = stmt.where(Requirement.coverage_status == coverage)
    if req_type:
        stmt = stmt.where(Requirement.req_type == req_type)
    return stmt.order_by(Requirement.id)


# ── Full pages ────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    asil: Optional[str] = None,
    coverage: Optional[str] = None,
    req_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = _apply_filters(select(Requirement), asil, coverage, req_type)
    reqs = db.scalars(stmt).all()

    covered = sum(1 for r in reqs if r.coverage_status == CoverageStatus.COVERED)
    at_risk = sum(1 for r in reqs if r.coverage_status == CoverageStatus.AT_RISK)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "requirements": reqs,
            "covered": covered,
            "at_risk": at_risk,
            "asil_filter": asil or "",
            "coverage_filter": coverage or "",
            "req_type_filter": req_type or "",
            "asil_levels": [e.value for e in ASILLevel],
            "coverage_statuses": [e.value for e in CoverageStatus],
            "req_types": [e.value for e in RequirementType],
        },
    )


# ── HTMX partials ─────────────────────────────────────────────────────────────

@router.get("/partials/requirements", response_class=HTMLResponse)
async def req_rows_partial(
    request: Request,
    asil: Optional[str] = None,
    coverage: Optional[str] = None,
    req_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = _apply_filters(select(Requirement), asil, coverage, req_type)
    reqs = db.scalars(stmt).all()
    return templates.TemplateResponse(
        request=request,
        name="partials/req_rows.html",
        context={"requirements": reqs},
    )


@router.get("/partials/requirements/{req_id}", response_class=HTMLResponse)
async def req_detail_partial(
    req_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    req = db.get(Requirement, req_id)
    if req is None:
        return HTMLResponse(
            "<p class='text-red-500 p-4'>Requirement not found.</p>", status_code=404
        )

    # Walk ancestor chain (parent → root)
    ancestors = []
    cursor = req
    seen = {req.id}
    while cursor.parent_id:
        if cursor.parent_id in seen:
            break
        parent = db.get(Requirement, cursor.parent_id)
        if parent is None:
            break
        ancestors.append(parent)
        seen.add(parent.id)
        cursor = parent

    return templates.TemplateResponse(
        request=request,
        name="partials/req_detail.html",
        context={
            "req": req,
            "ancestors": ancestors,
            "test_cases": req.test_cases,
            "defects": req.defects,
            "children": req.children,
        },
    )


@router.post("/partials/validate/{req_id}", response_class=HTMLResponse)
async def validate_partial(
    req_id: str,
    request: Request,
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    engine = ValidationEngine(session=db, embedder=embedder)
    try:
        result = await asyncio.to_thread(engine.validate_requirement, req_id)
    except ValueError as exc:
        return HTMLResponse(
            f"<p class='text-red-500 p-2 text-xs'>Validation failed: {exc}</p>",
            status_code=422,
        )
    return templates.TemplateResponse(
        request=request,
        name="partials/validation_result.html",
        context={"result": result},
    )


# ── File ingest ───────────────────────────────────────────────────────────────

@router.post("/ingest")
async def ingest_upload(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    embedder: KBEmbedder = Depends(get_embedder),
):
    suffix = Path(file.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        await asyncio.to_thread(ingest_file, tmp_path, None, db, embedder)
    except Exception:
        pass  # log but don't block redirect
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    return RedirectResponse("/", status_code=303)
