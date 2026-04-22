"""
ISO 26262 Validation Engine — core validation logic.

Calls claude-sonnet-4-6 with a cached system prompt, parses the structured
JSON response, and persists coverage_status back to SQLite.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..kb_ingestor.embedder import KBEmbedder
from ..kb_ingestor.models import Requirement
from .context_builder import ContextBuilder, ValidationContext
from .prompts import SYSTEM_PROMPT, VALIDATION_PROMPT_TEMPLATE
from .result_models import (
    DefectRiskResult,
    QualityResult,
    SafetyChainResult,
    TraceabilityResult,
    ValidationResult,
)

log = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 2048


# ── Prompt builder ────────────────────────────────────────────────────────────

def _build_prompt(ctx: ValidationContext) -> str:
    req = ctx.requirement

    # Safety chain: full ancestor list, ordered parent → root
    chain_lines: List[str] = []
    if ctx.ancestors:
        for anc in ctx.ancestors:
            chain_lines.append(
                f"  Ancestor ({anc['req_type']}): {anc['id']} — {anc['title']}"
            )
    else:
        chain_lines.append("  (no parent — top-level requirement)")
    chain_lines.append(
        f"  THIS ({req['req_type']}): {req['id']} — {req['title']}"
    )
    if ctx.children:
        for c in ctx.children:
            chain_lines.append(
                f"  Child ({c['req_type']}): {c['id']} — {c['title']}"
            )
    else:
        chain_lines.append("  (no children)")

    # ASIL decomposition partner section
    decomp_section = ""
    if req.get("asil_decomposition") and ctx.decomposition_partner:
        p = ctx.decomposition_partner
        decomp_section = (
            f"\n## ASIL Decomposition Partner\n"
            f"Partner ID: {p['id']}\n"
            f"Partner ASIL: {p['asil_level']}\n"
            f"Partner Type: {p['req_type']}\n"
            f"Partner Coverage: {p['coverage_status']}\n"
            f"Partner Chain Complete: see partner's safety_chain\n"
        )
    elif req.get("asil_decomposition"):
        partner_id = req.get("decomposition_partner_id") or "unknown"
        decomp_section = (
            f"\n## ASIL Decomposition Partner\n"
            f"Partner ID: {partner_id} (not found in KB — decomposition cannot be validated)\n"
        )

    # Test coverage summary by level (direct linked tests only)
    level_map: Dict[str, Dict[str, int]] = {}
    for tc in ctx.linked_tests:
        lvl = tc["level"]
        if lvl not in level_map:
            level_map[lvl] = {"Pass": 0, "Fail": 0, "other": 0}
        v = tc["verdict"]
        if v == "Pass":
            level_map[lvl]["Pass"] += 1
        elif v == "Fail":
            level_map[lvl]["Fail"] += 1
        else:
            level_map[lvl]["other"] += 1

    if level_map:
        summary_lines = []
        for lvl, counts in level_map.items():
            summary_lines.append(
                f"  {lvl}: {counts['Pass']} Pass, {counts['Fail']} Fail, "
                f"{counts['other']} Not Run/Blocked"
            )
        coverage_summary = "\n".join(summary_lines)
    else:
        coverage_summary = "  (no directly linked test cases)"

    # Test cases section — include steps/expected_result for traceability evaluation
    tc_lines: List[str] = []
    for tc in ctx.linked_tests:
        tc_lines.append(
            f"[LINKED] {tc['id']}: {tc['title']}"
            f" | Level: {tc['level']}"
            f" | State: {tc['lifecycle_state']}"
            f" | Verdict: {tc['verdict']}"
        )
        if tc.get("steps"):
            tc_lines.append(f"  Steps: {tc['steps'][:200]}")
        if tc.get("expected_result"):
            tc_lines.append(f"  Expected: {tc['expected_result'][:200]}")
    for tc in ctx.semantic_tests:
        sim = tc.get("similarity", 0.0)
        snippet = (tc.get("text") or "")[:100]
        tc_lines.append(f"[SIMILAR sim={sim:.2f}] {tc['id']}: {snippet}")

    # Defects section
    def_lines: List[str] = []
    for d in ctx.linked_defects:
        def_lines.append(
            f"[LINKED] {d['id']}: {d['summary']}"
            f" | Severity: {d['severity']}"
            f" | Status: {d['status']}"
        )
    for d in ctx.semantic_defects:
        sim = d.get("similarity", 0.0)
        snippet = (d.get("text") or d.get("summary") or "")[:100]
        def_lines.append(f"[SIMILAR sim={sim:.2f}] {d['id']}: {snippet}")

    return VALIDATION_PROMPT_TEMPLATE.format(
        req_id=req["id"],
        req_type=req["req_type"],
        asil_level=req["asil_level"],
        title=req["title"],
        text=req["text"],
        asil_decomposition=str(req.get("asil_decomposition", False)),
        safety_chain_section="\n".join(chain_lines),
        decomposition_section=decomp_section,
        coverage_summary_section=coverage_summary,
        linked_test_count=len(ctx.linked_tests),
        semantic_test_count=len(ctx.semantic_tests),
        test_cases_section="\n".join(tc_lines) if tc_lines else "(none)",
        linked_defect_count=len(ctx.linked_defects),
        semantic_defect_count=len(ctx.semantic_defects),
        defects_section="\n".join(def_lines) if def_lines else "(none)",
    )


# ── Response parser ───────────────────────────────────────────────────────────

def _parse_response(req_id: str, raw: str, model: str) -> ValidationResult:
    """Deserialise Claude's JSON output into a typed ValidationResult.

    Tries strict JSON parsing first. Falls back to extracting the outermost
    JSON object (handles markdown fences and surrounding prose) using first-{
    last-} extraction, which correctly handles nested structures unlike regex.
    """
    text = raw.strip()
    data: Optional[dict] = None

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Extract between the outermost { and } — robust against nested keys
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass

    if data is None:
        raise ValueError(
            f"Cannot parse Claude response as JSON for {req_id}. "
            f"First 200 chars: {text[:200]!r}"
        )

    t = data.get("traceability", {})
    dr = data.get("defect_risk", {})
    q = data.get("quality", {})
    sc = data.get("safety_chain", {})

    return ValidationResult(
        requirement_id=req_id,
        traceability=TraceabilityResult(
            covered=bool(t.get("covered", False)),
            linked_test_ids=list(t.get("linked_test_ids", [])),
            missing_levels=list(t.get("missing_levels", [])),
            verdict_summary=str(t.get("verdict_summary", "")),
            notes=str(t.get("notes", "")),
        ),
        defect_risk=DefectRiskResult(
            risk_level=str(dr.get("risk_level", "Medium")),
            open_defect_count=int(dr.get("open_defect_count", 0)),
            critical_defect_ids=list(dr.get("critical_defect_ids", [])),
            assessment=str(dr.get("assessment", "")),
        ),
        quality=QualityResult(
            score=int(q.get("score", 50)),
            issues=list(q.get("issues", [])),
            suggestions=list(q.get("suggestions", [])),
        ),
        safety_chain=SafetyChainResult(
            chain_complete=bool(sc.get("chain_complete", False)),
            asil_level=str(sc.get("asil_level", "QM")),
            parent_id=sc.get("parent_id"),
            children_ids=list(sc.get("children_ids", [])),
            gaps=list(sc.get("gaps", [])),
            decomposition_valid=bool(sc.get("decomposition_valid", True)),
        ),
        overall_verdict=str(data.get("overall_verdict", "Warning")),
        coverage_status=str(data.get("coverage_status", "Pending")),
        raw_response=raw,
        model_used=model,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


# ── Engine ────────────────────────────────────────────────────────────────────

class ValidationEngine:
    """Validates ISO 26262 requirements using Claude with prompt caching.

    The system prompt is marked cache_control=ephemeral so Anthropic caches it
    across all per-requirement calls in a session, substantially reducing token
    cost when validating large requirement sets.
    """

    def __init__(
        self,
        session: Session,
        embedder: KBEmbedder,
        api_key: Optional[str] = None,
        model: str = _DEFAULT_MODEL,
        _client: Optional[anthropic.Anthropic] = None,
        _context_builder: Optional[ContextBuilder] = None,
    ) -> None:
        # _client and _context_builder can be injected for testing
        self._client = _client or anthropic.Anthropic(api_key=api_key)
        self._session = session
        self._embedder = embedder
        self._model = model
        self._context_builder = _context_builder or ContextBuilder(session, embedder)

    # ── Cached system prompt block ────────────────────────────────────────────

    @staticmethod
    def _system_block() -> List[dict]:
        return [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    # ── Per-requirement validation ────────────────────────────────────────────

    def validate_requirement(self, req_id: str) -> ValidationResult:
        """Validate a single requirement and persist its coverage_status."""
        context = self._context_builder.build(req_id)
        prompt = _build_prompt(context)
        log.debug("Validating %s — prompt length: %d chars", req_id, len(prompt))

        response = self._client.messages.create(
            model=self._model,
            max_tokens=_MAX_TOKENS,
            system=self._system_block(),
            messages=[{"role": "user", "content": prompt}],
        )

        if not response.content:
            raise ValueError(
                f"Anthropic returned empty content for {req_id}"
            )

        raw = response.content[0].text
        log.debug("Claude response for %s (first 300 chars): %s", req_id, raw[:300])

        result = _parse_response(req_id, raw, self._model)

        # Persist the computed coverage_status back to the requirement row.
        # Rollback on commit failure so the session stays usable.
        req = self._session.get(Requirement, req_id)
        if req is not None:
            req.coverage_status = result.coverage_status
            try:
                self._session.commit()
            except Exception:
                self._session.rollback()
                raise

        return result

    # ── Batch validation ──────────────────────────────────────────────────────

    def validate_all(
        self,
        asil_filter: Optional[List[str]] = None,
    ) -> List[ValidationResult]:
        """Validate every requirement in the KB, optionally filtered by ASIL level.

        Individual errors are logged and skipped so the batch continues.
        """
        stmt = select(Requirement)
        if asil_filter:
            stmt = stmt.where(Requirement.asil_level.in_(asil_filter))
        reqs = self._session.scalars(stmt).all()

        results: List[ValidationResult] = []
        for req in reqs:
            try:
                result = self.validate_requirement(req.id)
                results.append(result)
                log.info(
                    "Validated %s [ASIL-%s] → %s",
                    req.id, req.asil_level, result.overall_verdict,
                )
            except anthropic.RateLimitError:
                log.warning("Rate limit reached while validating %s — skipping", req.id)
            except anthropic.APIError as exc:
                log.error("Anthropic API error validating %s: %s", req.id, exc)
            except ValueError as exc:
                log.error("Response parse error for %s: %s", req.id, exc)
            except Exception as exc:
                log.error("Unexpected error validating %s: %s", req.id, exc)

        return results
