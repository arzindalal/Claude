"""
Export endpoints — serve Excel workbook and CSV snapshots.

  GET /api/export/excel   — full multi-sheet .xlsx workbook
  GET /api/export/csv     — flat requirements CSV
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...export.report import ReportGenerator
from ..deps import get_db

router = APIRouter()


@router.get("/export/excel", tags=["Export"])
async def export_excel(db: Session = Depends(get_db)):
    """Download the full validation report as a multi-sheet Excel workbook."""
    generator = ReportGenerator(session=db)
    xlsx_bytes = await asyncio.to_thread(generator.generate_excel)
    return Response(
        content=xlsx_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=iso26262_validation_report.xlsx"},
    )


@router.get("/export/csv", tags=["Export"])
async def export_csv(db: Session = Depends(get_db)):
    """Download the requirements as a flat CSV file."""
    generator = ReportGenerator(session=db)
    csv_str = await asyncio.to_thread(generator.generate_requirements_csv)
    return Response(
        content=csv_str.encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=requirements.csv"},
    )
