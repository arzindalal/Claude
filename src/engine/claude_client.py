"""
Thin Anthropic SDK wrapper used by the validation and generation engines.

Key design points:

- Uses `claude-opus-4-7` by default for validation — adaptive thinking plus the
  model's reasoning depth are needed for multi-artefact traceability checks.
  A cheaper `SCREENING_MODEL` (Haiku 4.5) is exposed for bulk classification
  passes (e.g. "is this requirement ambiguous?").
- Prompt caching is applied to the standards-clauses / system-prompt prefix.
  These are stable across requests; the varying requirement text goes AFTER
  the last cache breakpoint. See `shared/prompt-caching.md` for the invariant.
- Structured outputs via `messages.parse()` with Pydantic models. Eliminates
  JSON parsing boilerplate and guarantees the engine never sees malformed
  output.
- The engine code (Phase 2) calls `validate_requirement(req, context)` and
  `generate_test_case(req, similar_tcs, context)` — both return typed records.

Phase-1 stub: schemas and client are wired, validation logic arrives in Phase 2.
"""

from __future__ import annotations

from typing import Optional

from anthropic import Anthropic
from pydantic import BaseModel, Field

from src.config import settings
from src.engine.prompts import (
    ISO26262_TESTCASE_GEN_SYSTEM,
    ISO26262_VALIDATION_SYSTEM,
)


# ---------------------------------------------------------------------------
# Structured output schemas
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """A KB ID + the exact quoted span supporting a verdict."""

    source_id: str = Field(..., description="Requirement / test / defect / clause ID")
    quote: str = Field(..., description="Literal substring from the source text")


class Verdict(BaseModel):
    requirement_id: str
    status: str = Field(
        ...,
        description="COVERED | PARTIALLY_COVERED | NOT_COVERED | AT_RISK",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str
    evidence: list[Evidence] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="Actionable gap descriptions for the report",
    )


class GeneratedTestCase(BaseModel):
    status: str = Field(..., description="NEW | EXISTING | UNTESTABLE")
    existing_test_case_id: Optional[str] = None
    untestable_reason: Optional[str] = None
    # Populated only when status == NEW
    title: Optional[str] = None
    objective: Optional[str] = None
    preconditions: Optional[str] = None
    steps: Optional[str] = None
    expected_result: Optional[str] = None
    asil_coverage_hint: Optional[str] = None
    source_requirement_id: Optional[str] = None
    grounding_quote: Optional[str] = Field(
        default=None,
        description="The literal substring of the requirement text the TC is grounded in",
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None) -> None:
        self._client = Anthropic(api_key=api_key or settings.anthropic_api_key or None)

    def validate_requirement(
        self,
        requirement_text: str,
        requirement_id: str,
        retrieved_context: str,
        *,
        model: Optional[str] = None,
    ) -> Verdict:
        """
        Run one validation pass against the retrieved KB context.

        The system prompt + retrieved_context form the stable prefix we cache;
        the requirement being assessed is the tail. Keep that ordering if you
        refactor — flipping it voids the cache.
        """
        model = model or settings.validation_model
        response = self._client.messages.parse(
            model=model,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": ISO26262_VALIDATION_SYSTEM,
                },
                {
                    "type": "text",
                    "text": f"RETRIEVED KB CONTEXT:\n\n{retrieved_context}",
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Assess requirement {requirement_id}.\n\n"
                        f"Requirement text:\n{requirement_text}\n\n"
                        "Return exactly one Verdict per the schema."
                    ),
                }
            ],
            output_format=Verdict,
        )
        return response.parsed_output

    def generate_test_case(
        self,
        requirement_text: str,
        requirement_id: str,
        similar_existing: str,
        *,
        model: Optional[str] = None,
    ) -> GeneratedTestCase:
        model = model or settings.validation_model
        response = self._client.messages.parse(
            model=model,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": ISO26262_TESTCASE_GEN_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Requirement ID: {requirement_id}\n"
                        f"Requirement text:\n{requirement_text}\n\n"
                        f"Similar existing test cases retrieved from KB:\n{similar_existing}\n\n"
                        "Return exactly one GeneratedTestCase per the schema."
                    ),
                }
            ],
            output_format=GeneratedTestCase,
        )
        return response.parsed_output
