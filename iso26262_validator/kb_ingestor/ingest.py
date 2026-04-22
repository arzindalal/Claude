"""
CLI for ingesting knowledge-base artifacts into SQLite + ChromaDB.

Usage examples
--------------
  # Ingest a requirements CSV explicitly
  python -m kb_ingestor.ingest --file data/requirements.csv --type requirements

  # Ingest a test-cases CSV
  python -m kb_ingestor.ingest --file data/test_cases.csv --type test_cases

  # Ingest a multi-sheet DOORS/Cradle workbook (auto-detected)
  python -m kb_ingestor.ingest --file data/doors_export.xlsx

  # Ingest every supported file in a directory
  python -m kb_ingestor.ingest --dir data/artifacts/

  # Custom DB / vector-store paths
  python -m kb_ingestor.ingest --file data/req.csv --type requirements \\
      --db /opt/kb/kb.sqlite --chroma /opt/kb/chroma
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from .database import get_engine, get_session
from .embedder import KBEmbedder
from .models import Defect, Requirement, TestCase
from .parsers.csv_parser import (
    parse_defects_csv,
    parse_requirements_csv,
    parse_test_cases_csv,
)
from .parsers.excel_parser import parse_excel

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

ArtifactType = str | None  # "requirements" | "test_cases" | "defects" | None


# ── Per-type ingest functions ─────────────────────────────────────────────────

def ingest_requirements(
    records: list[dict], session: Session, embedder: KBEmbedder
) -> int:
    """Upsert requirement records into SQLite and ChromaDB. Returns new-record count."""
    new_count = 0
    embed_batch: list[dict] = []

    for r in records:
        existing = session.get(Requirement, r["id"])
        if existing:
            for key, val in r.items():
                if key != "id" and hasattr(existing, key):
                    setattr(existing, key, val)
        else:
            session.add(
                Requirement(
                    id=r["id"],
                    text=r["text"],
                    title=r.get("title", ""),
                    source_file=r.get("source_file", ""),
                    asil_level=r.get("asil_level", "QM"),
                    req_type=r.get("req_type", "Functional"),
                    status=r.get("status", "Active"),
                    parent_id=r.get("parent_id"),
                )
            )
            new_count += 1

        embed_batch.append({
            "id": r["id"],
            "text": f"{r.get('title', '')} {r['text']}".strip(),
            "metadata": {
                "asil_level": r.get("asil_level", "QM"),
                "req_type": r.get("req_type", "Functional"),
                "source_file": r.get("source_file", ""),
            },
        })

    session.commit()
    embedder.add_requirements(embed_batch)
    return new_count


def ingest_test_cases(
    records: list[dict], session: Session, embedder: KBEmbedder
) -> int:
    """Upsert test-case records and wire Requirement ↔ TestCase links."""
    new_count = 0
    embed_batch: list[dict] = []

    for t in records:
        existing = session.get(TestCase, t["id"])
        if existing:
            for key, val in t.items():
                if key not in ("id", "linked_req_ids") and hasattr(existing, key):
                    setattr(existing, key, val)
            tc = existing
        else:
            tc = TestCase(
                id=t["id"],
                title=t["title"],
                objective=t.get("objective", ""),
                preconditions=t.get("preconditions", ""),
                steps=t.get("steps", ""),
                expected_result=t.get("expected_result", ""),
                level=t.get("level", "System"),
                status=t.get("status", "Open"),
                source_file=t.get("source_file", ""),
            )
            session.add(tc)
            new_count += 1

        for req_id in t.get("linked_req_ids", []):
            req = session.get(Requirement, req_id)
            if req is not None and tc not in req.test_cases:
                req.test_cases.append(tc)

        steps_text = t.get("steps", "")
        embed_batch.append({
            "id": t["id"],
            "text": " ".join(filter(None, [
                t["title"],
                t.get("objective", ""),
                steps_text,
                t.get("expected_result", ""),
            ])),
            "metadata": {
                "level": t.get("level", "System"),
                "status": t.get("status", "Open"),
                "source_file": t.get("source_file", ""),
                "linked_req_ids": ",".join(t.get("linked_req_ids", [])),
            },
        })

    session.commit()
    embedder.add_test_cases(embed_batch)
    return new_count


def ingest_defects(
    records: list[dict], session: Session, embedder: KBEmbedder
) -> int:
    """Upsert defect records and wire Requirement ↔ Defect links."""
    new_count = 0
    embed_batch: list[dict] = []

    for d in records:
        existing = session.get(Defect, d["id"])
        if existing:
            for key, val in d.items():
                if key not in ("id", "linked_req_ids") and hasattr(existing, key):
                    setattr(existing, key, val)
            defect = existing
        else:
            defect = Defect(
                id=d["id"],
                summary=d["summary"],
                description=d.get("description", ""),
                severity=d.get("severity", "Medium"),
                status=d.get("status", "Open"),
                source_file=d.get("source_file", ""),
            )
            session.add(defect)
            new_count += 1

        for req_id in d.get("linked_req_ids", []):
            req = session.get(Requirement, req_id)
            if req is not None and defect not in req.defects:
                req.defects.append(defect)

        embed_batch.append({
            "id": d["id"],
            "text": f"{d['summary']} {d.get('description', '')}".strip(),
            "metadata": {
                "severity": d.get("severity", "Medium"),
                "status": d.get("status", "Open"),
                "source_file": d.get("source_file", ""),
                "linked_req_ids": ",".join(d.get("linked_req_ids", [])),
            },
        })

    session.commit()
    embedder.add_defects(embed_batch)
    return new_count


# ── Auto-detect CSV type ──────────────────────────────────────────────────────

def _detect_csv_type(file_path: str) -> ArtifactType:
    """Infer artifact type from column headers (no data read)."""
    import pandas as pd

    df = pd.read_csv(file_path, nrows=0, dtype=str)
    cols = {c.lower().strip() for c in df.columns}

    if cols & {"steps", "test_steps", "procedure", "expected_result", "expected result", "pass criteria"}:
        return "test_cases"
    if cols & {"severity", "resolution", "issue_id", "jira_id"}:
        return "defects"
    # Fall back to requirements — will raise if mandatory cols are absent
    return "requirements"


# ── File-level dispatcher ─────────────────────────────────────────────────────

def ingest_file(
    file_path: str,
    artifact_type: ArtifactType,
    session: Session,
    embedder: KBEmbedder,
) -> None:
    path = Path(file_path)
    suffix = path.suffix.lower()
    log.info("Ingesting: %s", path.name)

    if suffix in (".xlsx", ".xls"):
        data = parse_excel(file_path)
        r = ingest_requirements(data["requirements"], session, embedder)
        t = ingest_test_cases(data["test_cases"], session, embedder)
        d = ingest_defects(data["defects"], session, embedder)
        log.info("  → %d requirements, %d test cases, %d defects (new)", r, t, d)
        return

    if suffix == ".csv":
        resolved_type = artifact_type or _detect_csv_type(file_path)
        if resolved_type == "requirements":
            records = parse_requirements_csv(file_path)
            n = ingest_requirements(records, session, embedder)
            log.info("  → %d new requirements (%d total)", n, len(records))
        elif resolved_type == "test_cases":
            records = parse_test_cases_csv(file_path)
            n = ingest_test_cases(records, session, embedder)
            log.info("  → %d new test cases (%d total)", n, len(records))
        elif resolved_type == "defects":
            records = parse_defects_csv(file_path)
            n = ingest_defects(records, session, embedder)
            log.info("  → %d new defects (%d total)", n, len(records))
        return

    log.warning("Skipping unsupported file type: %s", path.name)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m kb_ingestor.ingest",
        description="Ingest artifacts into the ISO 26262 Validation Tool knowledge base",
    )
    p.add_argument("--file", "-f", help="Path to a single CSV or Excel file")
    p.add_argument("--dir", "-d", help="Directory — ingest all supported files inside")
    p.add_argument(
        "--type", "-t",
        dest="artifact_type",
        choices=["requirements", "test_cases", "defects"],
        help="Artifact type for CSV files (auto-detected if omitted; Excel is always auto-detected)",
    )
    p.add_argument("--db", default="data/kb.sqlite", help="SQLite DB path (default: data/kb.sqlite)")
    p.add_argument("--chroma", default="data/chroma", help="ChromaDB storage path (default: data/chroma)")
    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if not args.file and not args.dir:
        log.error("Provide at least one of --file or --dir")
        sys.exit(1)

    engine = get_engine(args.db)
    session = get_session(engine)
    embedder = KBEmbedder(chroma_path=args.chroma)

    try:
        if args.file:
            ingest_file(args.file, args.artifact_type, session, embedder)

        if args.dir:
            dir_path = Path(args.dir)
            files = sorted(f for f in dir_path.iterdir() if f.suffix.lower() in _SUPPORTED_EXTENSIONS)
            if not files:
                log.warning("No supported files found in %s", args.dir)
            for f in files:
                try:
                    ingest_file(str(f), args.artifact_type, session, embedder)
                except Exception as exc:
                    log.error("Failed to ingest %s: %s", f.name, exc)

        # Summary
        req_total = session.query(Requirement).count()
        tc_total = session.query(TestCase).count()
        def_total = session.query(Defect).count()
        vec_counts = embedder.counts()
        log.info("")
        log.info("Knowledge Base Summary")
        log.info("  SQLite   — Requirements: %d | Test Cases: %d | Defects: %d", req_total, tc_total, def_total)
        log.info(
            "  ChromaDB — Requirements: %d | Test Cases: %d | Defects: %d",
            vec_counts["requirements"], vec_counts["test_cases"], vec_counts["defects"],
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
