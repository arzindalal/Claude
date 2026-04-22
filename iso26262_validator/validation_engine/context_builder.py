"""
RAG context builder for the ISO 26262 Validation Engine.

Combines SQLite relationship traversal (full ancestor chain, ASIL decomposition
partner, linked tests/defects) with ChromaDB semantic search to produce a rich
ValidationContext for each requirement being validated.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..kb_ingestor.embedder import KBEmbedder
from ..kb_ingestor.models import Defect, Requirement, TestCase

log = logging.getLogger(__name__)


# ── Thin projection dicts (avoid passing ORM objects across session boundaries) ─

def _req_to_dict(req: Requirement) -> dict:
    return {
        "id": req.id,
        "text": req.text,
        "title": req.title or "",
        "asil_level": req.asil_level,
        "req_type": req.req_type,
        "status": req.status,
        "parent_id": req.parent_id,
        "asil_decomposition": req.asil_decomposition,
        "decomposition_partner_id": req.decomposition_partner_id,
        "coverage_status": req.coverage_status,
    }


def _tc_to_dict(tc: TestCase) -> dict:
    return {
        "id": tc.id,
        "title": tc.title,
        "objective": tc.objective or "",
        "steps": tc.steps or "",
        "expected_result": tc.expected_result or "",
        "level": tc.level,
        "verification_method": tc.verification_method,
        "lifecycle_state": tc.lifecycle_state,
        "verdict": tc.verdict,
    }


def _defect_to_dict(d: Defect) -> dict:
    return {
        "id": d.id,
        # "text" is included so _build_prompt() can use a uniform snippet key
        "text": d.summary,
        "summary": d.summary,
        "description": d.description or "",
        "severity": d.severity,
        "status": d.status,
    }


# ── Context container ─────────────────────────────────────────────────────────

@dataclass
class ValidationContext:
    requirement: dict
    # Full ancestor chain ordered parent → root (e.g. TSR → FSR → Safety Goal).
    # Supports hierarchies deeper than 2 levels (the full SG→FSR→TSR→SSR chain).
    ancestors: List[dict]
    children: List[dict]
    # Sibling branch in an ASIL decomposition (ISO 26262-9), if applicable.
    decomposition_partner: Optional[dict]
    linked_tests: List[dict]
    semantic_tests: List[dict]    # ChromaDB hits not already in linked_tests
    linked_defects: List[dict]
    semantic_defects: List[dict]  # ChromaDB hits not already in linked_defects


# ── Builder ───────────────────────────────────────────────────────────────────

class ContextBuilder:
    # Fetch more candidates than needed; filter already-linked, then cap.
    _SEMANTIC_CANDIDATES = 8
    _SEMANTIC_MAX = 3

    def __init__(self, session: Session, embedder: KBEmbedder) -> None:
        self._session = session
        self._embedder = embedder

    def build(self, req_id: str) -> ValidationContext:
        # Eager-load M2M relationships in a single round-trip to avoid N+1
        # queries and DetachedInstanceError if the session is reused externally.
        stmt = (
            select(Requirement)
            .where(Requirement.id == req_id)
            .options(
                selectinload(Requirement.test_cases),
                selectinload(Requirement.defects),
                selectinload(Requirement.children),
            )
        )
        req = self._session.scalars(stmt).first()
        if req is None:
            raise ValueError(f"Requirement {req_id!r} not found in knowledge base")

        query_text = f"{req.title or ''} {req.text}".strip()

        # Walk the full ancestor chain to the root Safety Goal.
        # Two-level grandparent access misses the SG for 4-level hierarchies.
        ancestors: List[dict] = []
        cursor = req
        seen: set = {req.id}
        while cursor.parent_id:
            if cursor.parent_id in seen:
                log.warning("Cycle detected in ancestor chain at %s", cursor.id)
                break
            parent = self._session.get(Requirement, cursor.parent_id)
            if parent is None:
                log.warning(
                    "Requirement %s has parent_id=%s but parent not found (broken FK?)",
                    cursor.id, cursor.parent_id,
                )
                break
            ancestors.append(_req_to_dict(parent))
            seen.add(parent.id)
            cursor = parent

        # ASIL decomposition partner (ISO 26262-9)
        decomp_partner: Optional[dict] = None
        if req.asil_decomposition and req.decomposition_partner_id:
            partner = self._session.get(Requirement, req.decomposition_partner_id)
            if partner is not None:
                decomp_partner = _req_to_dict(partner)
            else:
                log.warning(
                    "Decomposition partner %s for %s not found",
                    req.decomposition_partner_id, req_id,
                )

        children = [_req_to_dict(c) for c in req.children]

        # Directly linked test cases (M2M via req_test_link)
        linked_tests = [_tc_to_dict(tc) for tc in req.test_cases]
        linked_test_ids = {tc["id"] for tc in linked_tests}

        # Semantic search — exclude already-linked IDs
        raw_semantic_tests = self._embedder.query_similar_tests(
            query_text, n_results=self._SEMANTIC_CANDIDATES
        )
        semantic_tests = [
            t for t in raw_semantic_tests if t["id"] not in linked_test_ids
        ][:self._SEMANTIC_MAX]

        # Directly linked defects (M2M via req_defect_link)
        linked_defects = [_defect_to_dict(d) for d in req.defects]
        linked_defect_ids = {d["id"] for d in linked_defects}

        # Semantic search — exclude already-linked IDs
        raw_semantic_defects = self._embedder.query_related_defects(
            query_text, n_results=self._SEMANTIC_CANDIDATES
        )
        semantic_defects = [
            d for d in raw_semantic_defects if d["id"] not in linked_defect_ids
        ][:self._SEMANTIC_MAX]

        return ValidationContext(
            requirement=_req_to_dict(req),
            ancestors=ancestors,
            children=children,
            decomposition_partner=decomp_partner,
            linked_tests=linked_tests,
            semantic_tests=semantic_tests,
            linked_defects=linked_defects,
            semantic_defects=semantic_defects,
        )
