"""
SQLAlchemy ORM models for the ISO 26262 validation knowledge base.

Hierarchy supported:
  Safety Goal (SG) → FSR → TSR → SSR  (via parent_id self-referential FK)
  Requirement ↔ TestCase              (many-to-many via req_test_link)
  Requirement ↔ Defect               (many-to-many via req_defect_link)
"""

import enum
from sqlalchemy import Boolean, Column, String, Text, ForeignKey, Table
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ── Association tables ────────────────────────────────────────────────────────

req_test_link = Table(
    "req_test_link",
    Base.metadata,
    Column("req_id", String, ForeignKey("requirements.id"), primary_key=True),
    Column("test_id", String, ForeignKey("test_cases.id"), primary_key=True),
)

req_defect_link = Table(
    "req_defect_link",
    Base.metadata,
    Column("req_id", String, ForeignKey("requirements.id"), primary_key=True),
    Column("defect_id", String, ForeignKey("defects.id"), primary_key=True),
)


# ── Enum constants (stored as plain strings for SQLite portability) ───────────

class ASILLevel(str, enum.Enum):
    QM = "QM"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class RequirementType(str, enum.Enum):
    FUNCTIONAL = "Functional"
    SAFETY = "Safety"
    NON_FUNCTIONAL = "Non-Functional"
    SAFETY_GOAL = "Safety Goal"
    FSR = "FSR"   # Functional Safety Requirement (ISO 26262 Part 4)
    TSR = "TSR"   # Technical Safety Requirement (ISO 26262 Part 4)
    SSR = "SSR"   # Software Safety Requirement (ISO 26262 Part 6)


class CoverageStatus(str, enum.Enum):
    COVERED = "Covered"
    PARTIALLY_COVERED = "Partially Covered"
    NOT_COVERED = "Not Covered"
    AT_RISK = "At Risk"
    PENDING = "Pending"


# ISO 26262 Part 6 test levels (§9–§12)
class TestLevel(str, enum.Enum):
    SW_UNIT = "SW Unit Testing"
    SW_INTEGRATION = "SW Integration Testing"
    SW_QUALIFICATION = "SW Qualification Testing"
    HW_SW_INTEGRATION = "HW/SW Integration Testing"


class TestLifecycleState(str, enum.Enum):
    DRAFT = "Draft"
    APPROVED = "Approved"
    READY = "Ready"
    EXECUTED = "Executed"


class TestVerdict(str, enum.Enum):
    NOT_RUN = "Not Run"
    PASS = "Pass"
    FAIL = "Fail"
    BLOCKED = "Blocked"
    NA = "N/A"


class VerificationMethod(str, enum.Enum):
    DYNAMIC_TEST = "Dynamic Test"
    SIMULATION = "Simulation"
    FORMAL_VERIFICATION = "Formal Verification"
    REVIEW = "Review"
    BACK_TO_BACK = "Back-to-Back Test"
    HIL = "HW-in-the-Loop"


# ── ORM Models ────────────────────────────────────────────────────────────────

class Requirement(Base):
    __tablename__ = "requirements"

    id = Column(String, primary_key=True)
    text = Column(Text, nullable=False)
    title = Column(String, default="")
    source_file = Column(String, default="")
    asil_level = Column(String, default=ASILLevel.QM)
    req_type = Column(String, default=RequirementType.FUNCTIONAL)
    status = Column(String, default="Active")
    coverage_status = Column(String, default=CoverageStatus.PENDING)

    # Self-referential FK for SG → FSR → TSR → SSR chain
    parent_id = Column(String, ForeignKey("requirements.id"), nullable=True)

    # ASIL decomposition tracking (ISO 26262-9): stores the ID of the partner branch
    asil_decomposition = Column(Boolean, default=False, nullable=False)
    decomposition_partner_id = Column(String, nullable=True)

    # many-to-one: child → parent
    parent = relationship(
        "Requirement",
        back_populates="children",
        foreign_keys=[parent_id],
        remote_side=[id],
    )
    # one-to-many: parent → children
    children = relationship(
        "Requirement",
        back_populates="parent",
        foreign_keys=[parent_id],
    )

    test_cases = relationship("TestCase", secondary=req_test_link, back_populates="requirements")
    defects = relationship("Defect", secondary=req_defect_link, back_populates="requirements")

    def __repr__(self) -> str:
        return f"<Requirement {self.id} [{self.asil_level}] {self.title!r}>"


class TestCase(Base):
    __tablename__ = "test_cases"

    id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    objective = Column(Text, default="")
    preconditions = Column(Text, default="")
    steps = Column(Text, default="")
    expected_result = Column(Text, default="")
    level = Column(String, default=TestLevel.SW_QUALIFICATION)
    verification_method = Column(String, default=VerificationMethod.DYNAMIC_TEST)
    lifecycle_state = Column(String, default=TestLifecycleState.DRAFT)
    verdict = Column(String, default=TestVerdict.NOT_RUN)
    source_file = Column(String, default="")

    requirements = relationship("Requirement", secondary=req_test_link, back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<TestCase {self.id} [{self.lifecycle_state}/{self.verdict}] {self.title!r}>"


class Defect(Base):
    __tablename__ = "defects"

    id = Column(String, primary_key=True)
    summary = Column(Text, nullable=False)
    description = Column(Text, default="")
    severity = Column(String, default="Medium")
    status = Column(String, default="Open")
    source_file = Column(String, default="")

    requirements = relationship("Requirement", secondary=req_defect_link, back_populates="defects")

    def __repr__(self) -> str:
        return f"<Defect {self.id} [{self.severity}] {self.summary!r}>"
