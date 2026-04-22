"""
SQLAlchemy ORM models for the ISO 26262 validation knowledge base.

Hierarchy supported:
  Safety Goal (SG) → TSR → SSR  (via parent_id self-referential FK)
  Requirement ↔ TestCase         (many-to-many via req_test_link)
  Requirement ↔ Defect           (many-to-many via req_defect_link)
"""

import enum
from sqlalchemy import Column, String, Text, ForeignKey, Table
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
    TSR = "TSR"
    SSR = "SSR"


class CoverageStatus(str, enum.Enum):
    COVERED = "Covered"
    PARTIALLY_COVERED = "Partially Covered"
    NOT_COVERED = "Not Covered"
    AT_RISK = "At Risk"
    PENDING = "Pending"


class TestLevel(str, enum.Enum):
    UNIT = "Unit"
    INTEGRATION = "Integration"
    SYSTEM = "System"
    ACCEPTANCE = "Acceptance"


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

    # Self-referential FK for SG → TSR → SSR chain
    parent_id = Column(String, ForeignKey("requirements.id"), nullable=True)

    children = relationship(
        "Requirement",
        backref="parent",  # type: ignore[call-arg]
        foreign_keys=[parent_id],
        remote_side="Requirement.id",
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
    level = Column(String, default=TestLevel.SYSTEM)
    status = Column(String, default="Open")
    source_file = Column(String, default="")

    requirements = relationship("Requirement", secondary=req_test_link, back_populates="test_cases")

    def __repr__(self) -> str:
        return f"<TestCase {self.id} {self.title!r}>"


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
