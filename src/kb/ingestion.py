"""
Top-level ingestion pipeline.

Walks a directory, classifies each file by stem (and extension for XML), dispatches
to the right parser, and upserts into the hybrid store. Errors on individual
files are collected in the IngestionSummary rather than aborting the whole run —
a solo builder wants partial progress, not an all-or-nothing rollback.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from src.kb.models import IngestionSummary, Requirement
from src.kb.parsers.cradle import parse_cradle_xml
from src.kb.parsers.tabular import classify, parse_any
from src.kb.store import KBStore


TABULAR_EXT = {".csv", ".xlsx", ".xlsm", ".xls"}


def ingest_path(path: Path, store: Optional[KBStore] = None) -> IngestionSummary:
    store = store or KBStore()
    summary = IngestionSummary()

    files = [path] if path.is_file() else sorted(
        p for p in path.rglob("*")
        if p.is_file() and p.suffix.lower() in TABULAR_EXT | {".xml"}
    )

    for f in files:
        try:
            _ingest_file(f, store, summary)
        except Exception as e:  # noqa: BLE001 — we want partial progress
            summary.errors.append(f"{f.name}: {e}")

    summary.finished_at = datetime.utcnow()
    return summary


def _ingest_file(f: Path, store: KBStore, summary: IngestionSummary) -> None:
    if f.suffix.lower() == ".xml":
        reqs: list[Requirement] = parse_cradle_xml(f)
        summary.requirements += store.upsert_requirements(reqs)
        return

    kind = classify(f)
    if not kind:
        # Not a recognised artefact file — skip silently (could be a README).
        return

    records = list(parse_any(f))
    if not records:
        return

    # parse_any returns a single concrete type per file; route accordingly.
    first = records[0]
    type_name = type(first).__name__
    if type_name == "Requirement":
        summary.requirements += store.upsert_requirements(records)
    elif type_name == "TestCase":
        summary.test_cases += store.upsert_test_cases(records)
    elif type_name == "Defect":
        summary.defects += store.upsert_defects(records)
