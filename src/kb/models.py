"""
Pydantic schemas for every artefact in the knowledge base.

Each record carries a stable source_ref (Cradle / DOORS / Jira ID) that is used
both as the SQLite primary key and as the traceability anchor when the
validation engine cites evidence. Nothing in the engine is allowed to invent
IDs — grounded evidence must refer to an ID that already exists in the KB.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ASIL(str, Enum):
    QM = "QM"
    A = "ASIL-A"
    B = "ASIL-B"
    C = "ASIL-C"
    D = "ASIL-D"


class ReqLevel(str, Enum):
    CUSTOMER = "customer"
    SYSTEM = "system"
    SW = "software"
    HW = "hardware"
    SAFETY_GOAL = "safety_goal"
    TSR = "tsr"  # Technical Safety Requirement
    SSR = "ssr"  # Software Safety Requirement


class TestLevel(str, Enum):
    UNIT = "unit"
    INTEGRATION = "integration"
    SYSTEM = "system"
    ACCEPTANCE = "acceptance"
    VALIDATION = "validation"


class DefectStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    VERIFIED = "verified"
    CLOSED = "closed"
    REJECTED = "rejected"


class Requirement(BaseModel):
    """A requirement of any level (customer → SG → TSR → SSR → SW)."""

    id: str = Field(..., description="Stable source ID, e.g. CUST-REQ-001")
    level: ReqLevel
    title: str
    text: str = Field(..., description="Full requirement text")
    asil: ASIL = ASIL.QM
    parent_id: Optional[str] = Field(
        default=None,
        description="Upstream requirement this one derives from (for SG→TSR→SSR chain)",
    )
    source: str = Field(default="", description="File or system of record")
    tags: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    id: str
    title: str
    level: TestLevel
    objective: str
    preconditions: str = ""
    steps: str = Field(..., description="Ordered, numbered steps")
    expected_result: str
    verifies_req_ids: list[str] = Field(
        default_factory=list,
        description="Requirement IDs this test case verifies (trace link)",
    )
    asil_coverage_hint: str = ""
    source: str = ""


class Defect(BaseModel):
    id: str
    title: str
    description: str
    status: DefectStatus
    severity: str = ""
    against_req_ids: list[str] = Field(default_factory=list)
    against_test_ids: list[str] = Field(default_factory=list)
    source: str = ""


class TraceLink(BaseModel):
    """Explicit trace edge: parent_id --(link_type)--> child_id."""

    parent_id: str
    child_id: str
    link_type: str = Field(
        default="verifies",
        description="e.g. derives, verifies, covers, implements",
    )


class StandardsClause(BaseModel):
    """A normative clause from ISO 26262 / ASPICE, indexed for RAG grounding."""

    id: str = Field(..., description="e.g. ISO26262-6:9.4.4")
    standard: str = Field(..., description="ISO26262 | ASPICE | ...")
    part: str = ""
    clause: str = ""
    title: str = ""
    text: str
    applicable_asil: list[ASIL] = Field(default_factory=list)


class IngestionSummary(BaseModel):
    """Returned by the ingestion pipeline — shown by the CLI after a run."""

    requirements: int = 0
    test_cases: int = 0
    defects: int = 0
    trace_links: int = 0
    standards_clauses: int = 0
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
