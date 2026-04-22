"""
Export layer — produces Excel workbooks and CSV snapshots of the validation KB.

Sheets in the Excel workbook
-----------------------------
  Summary            — aggregate stats with timestamp
  Requirements       — all requirements with coverage/ASIL/test counts
  Traceability Matrix — requirements × test-levels (pass/fail counts)
  Test Cases         — all test cases with linked requirement IDs
  Defects            — all defects with linked requirement IDs
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..kb_ingestor.models import (
    ASILLevel,
    CoverageStatus,
    Defect,
    Requirement,
    TestCase,
    TestLevel,
    TestVerdict,
)

# ── Colour palette (openpyxl ARGB hex, no alpha prefix needed for PatternFill) ─

_ASIL_FILL: Dict[str, str] = {
    "QM": "FFE2E2E2",  # grey
    "A": "FF90EE90",   # light green
    "B": "FFFFFF99",   # yellow
    "C": "FFFFA500",   # orange
    "D": "FFFF6B6B",   # red
}

_COVERAGE_FILL: Dict[str, str] = {
    CoverageStatus.COVERED: "FF90EE90",
    CoverageStatus.PARTIALLY_COVERED: "FFFFFF99",
    CoverageStatus.NOT_COVERED: "FFFF6B6B",
    CoverageStatus.AT_RISK: "FFFFA500",
    CoverageStatus.PENDING: "FFE2E2E2",
}

_VERDICT_FILL: Dict[str, str] = {
    TestVerdict.PASS: "FF90EE90",
    TestVerdict.FAIL: "FFFF6B6B",
    TestVerdict.BLOCKED: "FFFFA500",
    TestVerdict.NOT_RUN: "FFE2E2E2",
    TestVerdict.NA: "FFE2E2E2",
}

_HEADER_FILL = "FF4F81BD"   # blue header background
_HEADER_FONT_COLOR = "FFFFFFFF"


def _lazy_openpyxl():
    """Import openpyxl on demand so the module is importable without it."""
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
        return openpyxl, Alignment, Font, PatternFill, get_column_letter
    except ImportError as exc:  # pragma: no cover
        raise ImportError("openpyxl is required for Excel export: pip install openpyxl") from exc


class ReportGenerator:
    """Generate Excel and CSV reports from the validation knowledge base."""

    def __init__(self, session: Session) -> None:
        self._db = session

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_excel(self) -> bytes:
        """Return a bytes blob containing a multi-sheet .xlsx workbook."""
        openpyxl, Alignment, Font, PatternFill, get_column_letter = _lazy_openpyxl()

        reqs = self._load_requirements()
        tests = self._load_test_cases()
        defects = self._load_defects()

        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # remove the default blank sheet

        self._sheet_summary(wb, reqs, tests, defects, Font, PatternFill, Alignment, get_column_letter)
        self._sheet_requirements(wb, reqs, Font, PatternFill, Alignment, get_column_letter)
        self._sheet_traceability(wb, reqs, Font, PatternFill, Alignment, get_column_letter)
        self._sheet_test_cases(wb, tests, Font, PatternFill, Alignment, get_column_letter)
        self._sheet_defects(wb, defects, Font, PatternFill, Alignment, get_column_letter)

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def generate_requirements_csv(self) -> str:
        """Return a UTF-8 CSV string of all requirements."""
        reqs = self._load_requirements()
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "ID", "Title", "ASIL", "Type", "Status",
            "Coverage Status", "Parent ID", "Test Count",
            "Pass Count", "Fail Count", "Open Defect Count",
        ])
        for req in reqs:
            verdicts = [tc.verdict for tc in req.test_cases]
            writer.writerow([
                req.id,
                req.title or "",
                req.asil_level or "",
                req.req_type or "",
                req.status or "",
                req.coverage_status or "",
                req.parent_id or "",
                len(req.test_cases),
                verdicts.count(TestVerdict.PASS),
                verdicts.count(TestVerdict.FAIL),
                sum(1 for d in req.defects if d.status == "Open"),
            ])
        return buf.getvalue()

    # ── Data loading ───────────────────────────────────────────────────────────

    def _load_requirements(self) -> List[Requirement]:
        stmt = (
            select(Requirement)
            .options(
                selectinload(Requirement.test_cases),
                selectinload(Requirement.defects),
                selectinload(Requirement.children),
            )
            .order_by(Requirement.id)
        )
        return list(self._db.scalars(stmt).all())

    def _load_test_cases(self) -> List[TestCase]:
        stmt = (
            select(TestCase)
            .options(selectinload(TestCase.requirements))
            .order_by(TestCase.id)
        )
        return list(self._db.scalars(stmt).all())

    def _load_defects(self) -> List[Defect]:
        stmt = (
            select(Defect)
            .options(selectinload(Defect.requirements))
            .order_by(Defect.id)
        )
        return list(self._db.scalars(stmt).all())

    # ── Shared helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _style_header_row(ws, row_idx: int, Font, PatternFill):
        for cell in ws[row_idx]:
            cell.font = Font(bold=True, color=_HEADER_FONT_COLOR)
            cell.fill = PatternFill("solid", fgColor=_HEADER_FILL)

    @staticmethod
    def _auto_width(ws, get_column_letter):
        for col in ws.columns:
            max_len = max((len(str(c.value or "")) for c in col), default=0)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 60)

    @staticmethod
    def _color_cell(cell, color: str, PatternFill):
        if color:
            cell.fill = PatternFill("solid", fgColor=color)

    # ── Sheet builders ─────────────────────────────────────────────────────────

    def _sheet_summary(self, wb, reqs, tests, defects, Font, PatternFill, Alignment, get_column_letter):
        ws = wb.create_sheet("Summary")

        total = len(reqs)
        coverage_counts: Dict[str, int] = {}
        asil_counts: Dict[str, int] = {}
        for r in reqs:
            coverage_counts[r.coverage_status or "Pending"] = coverage_counts.get(r.coverage_status or "Pending", 0) + 1
            asil_counts[r.asil_level or "QM"] = asil_counts.get(r.asil_level or "QM", 0) + 1

        open_defects = sum(1 for d in defects if d.status == "Open")
        critical_defects = sum(1 for d in defects if d.status == "Open" and d.severity in ("Critical", "High"))

        rows = [
            ["ISO 26262 Validation Report"],
            ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
            [],
            ["== Requirements =="],
            ["Total Requirements", total],
        ]
        for status, count in sorted(coverage_counts.items()):
            pct = f"{count / total * 100:.1f}%" if total else "0%"
            rows.append([f"  {status}", count, pct])

        rows.append([])
        rows.append(["== ASIL Distribution =="])
        for level in [e.value for e in ASILLevel]:
            rows.append([f"  ASIL {level}", asil_counts.get(level, 0)])

        rows.extend([
            [],
            ["== Test Cases =="],
            ["Total Test Cases", len(tests)],
            ["  Pass", sum(1 for t in tests if t.verdict == TestVerdict.PASS)],
            ["  Fail", sum(1 for t in tests if t.verdict == TestVerdict.FAIL)],
            ["  Not Run", sum(1 for t in tests if t.verdict == TestVerdict.NOT_RUN)],
            [],
            ["== Defects =="],
            ["Total Defects", len(defects)],
            ["  Open", open_defects],
            ["  Open Critical/High", critical_defects],
        ])

        for row in rows:
            ws.append(row)

        # Style title row
        ws["A1"].font = Font(bold=True, size=14)
        self._auto_width(ws, get_column_letter)

    def _sheet_requirements(self, wb, reqs, Font, PatternFill, Alignment, get_column_letter):
        ws = wb.create_sheet("Requirements")
        headers = [
            "ID", "Title", "ASIL", "Type", "Status",
            "Coverage Status", "Parent ID",
            "Test Count", "Pass", "Fail", "Not Run", "Open Defects",
        ]
        ws.append(headers)
        self._style_header_row(ws, 1, Font, PatternFill)
        ws.freeze_panes = "A2"

        for req in reqs:
            verdicts = [tc.verdict for tc in req.test_cases]
            row = [
                req.id,
                req.title or "",
                req.asil_level or "",
                req.req_type or "",
                req.status or "",
                req.coverage_status or "",
                req.parent_id or "",
                len(req.test_cases),
                verdicts.count(TestVerdict.PASS),
                verdicts.count(TestVerdict.FAIL),
                verdicts.count(TestVerdict.NOT_RUN),
                sum(1 for d in req.defects if d.status == "Open"),
            ]
            ws.append(row)
            r = ws.max_row
            self._color_cell(ws.cell(r, 3), _ASIL_FILL.get(req.asil_level or "QM", ""), PatternFill)
            self._color_cell(ws.cell(r, 6), _COVERAGE_FILL.get(req.coverage_status or "", ""), PatternFill)

        self._auto_width(ws, get_column_letter)

    def _sheet_traceability(self, wb, reqs, Font, PatternFill, Alignment, get_column_letter):
        ws = wb.create_sheet("Traceability Matrix")
        levels = [e.value for e in TestLevel]
        headers = ["Req ID", "Title", "ASIL", "Coverage"] + levels
        ws.append(headers)
        self._style_header_row(ws, 1, Font, PatternFill)
        ws.freeze_panes = "A2"

        for req in reqs:
            level_pass: Dict[str, int] = {lv: 0 for lv in levels}
            level_fail: Dict[str, int] = {lv: 0 for lv in levels}
            for tc in req.test_cases:
                lv = tc.level or ""
                if lv in level_pass:
                    if tc.verdict == TestVerdict.PASS:
                        level_pass[lv] += 1
                    elif tc.verdict == TestVerdict.FAIL:
                        level_fail[lv] += 1

            level_cells = []
            for lv in levels:
                p, f = level_pass[lv], level_fail[lv]
                if p == 0 and f == 0:
                    level_cells.append("—")
                else:
                    level_cells.append(f"{p}P / {f}F")

            ws.append([req.id, req.title or "", req.asil_level or "", req.coverage_status or ""] + level_cells)
            r = ws.max_row
            self._color_cell(ws.cell(r, 3), _ASIL_FILL.get(req.asil_level or "QM", ""), PatternFill)
            self._color_cell(ws.cell(r, 4), _COVERAGE_FILL.get(req.coverage_status or "", ""), PatternFill)

            for col_offset, lv in enumerate(levels, start=5):
                p, f = level_pass[lv], level_fail[lv]
                cell = ws.cell(r, col_offset)
                if f > 0:
                    cell.fill = PatternFill("solid", fgColor=_VERDICT_FILL[TestVerdict.FAIL])
                elif p > 0:
                    cell.fill = PatternFill("solid", fgColor=_VERDICT_FILL[TestVerdict.PASS])

        self._auto_width(ws, get_column_letter)

    def _sheet_test_cases(self, wb, tests, Font, PatternFill, Alignment, get_column_letter):
        ws = wb.create_sheet("Test Cases")
        headers = [
            "ID", "Title", "Level", "Verification Method",
            "Lifecycle State", "Verdict", "Linked Requirement IDs",
        ]
        ws.append(headers)
        self._style_header_row(ws, 1, Font, PatternFill)
        ws.freeze_panes = "A2"

        for tc in tests:
            req_ids = ", ".join(r.id for r in tc.requirements)
            ws.append([
                tc.id,
                tc.title or "",
                tc.level or "",
                tc.verification_method or "",
                tc.lifecycle_state or "",
                tc.verdict or "",
                req_ids,
            ])
            r = ws.max_row
            self._color_cell(ws.cell(r, 6), _VERDICT_FILL.get(tc.verdict or "", ""), PatternFill)

        self._auto_width(ws, get_column_letter)

    def _sheet_defects(self, wb, defects, Font, PatternFill, Alignment, get_column_letter):
        ws = wb.create_sheet("Defects")
        headers = ["ID", "Summary", "Severity", "Status", "Linked Requirement IDs"]
        ws.append(headers)
        self._style_header_row(ws, 1, Font, PatternFill)
        ws.freeze_panes = "A2"

        _SEV_FILL = {
            "Critical": "FFFF0000",
            "High": "FFFF6B6B",
            "Medium": "FFFFA500",
            "Low": "FFFFFF99",
        }

        for defect in defects:
            req_ids = ", ".join(r.id for r in defect.requirements)
            ws.append([
                defect.id,
                defect.summary or "",
                defect.severity or "",
                defect.status or "",
                req_ids,
            ])
            r = ws.max_row
            self._color_cell(ws.cell(r, 3), _SEV_FILL.get(defect.severity or "", ""), PatternFill)

        self._auto_width(ws, get_column_letter)
