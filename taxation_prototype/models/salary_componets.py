import uuid
import enum

from sqlalchemy import (
    Column,
    String,
    Boolean,
    Integer,
    Text,
    Numeric,
    DateTime,
    Enum
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base


# -------------------------
# ENUMS
# -------------------------

class ComponentCategory(enum.Enum):
    EARNING = "EARNING"
    DEDUCTION = "DEDUCTION"
    EMPLOYER_CONTRIBUTION = "EMPLOYER_CONTRIBUTION"


class ComputationType(enum.Enum):
    FIXED = "FIXED"
    PERCENTAGE = "PERCENTAGE"
    FORMULA = "FORMULA"


# -------------------------
# MODEL
# -------------------------

class SalaryComponent(Base):
    __tablename__ = "salary_components"

    component_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name = Column(
        String(100),
        nullable=False
    )

    code = Column(
        String(30),
        unique=True,
        nullable=False
    )

    category = Column(
        Enum(ComponentCategory, name="component_category"),
        nullable=False
    )

    computation_type = Column(
        Enum(ComputationType, name="computation_type"),
        nullable=False
    )

    amount = Column(
        Numeric(12, 2),
        nullable=True
    )

    percentage = Column(
        Numeric(5, 2),
        nullable=True
    )

    percentage_of = Column(
        String(50),
        nullable=True
    )

    formula = Column(
        Text,
        nullable=True
    )

    sequence = Column(
        Integer,
        default=10,
        nullable=False
    )

    taxable = Column(
        Boolean,
        default=True,
        nullable=False
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
    )

    description = Column(
        Text,
        nullable=True
    )

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )

    # Relationship (will be used later)
    structure_components = relationship(
        "StructureComponent",
        back_populates="salary_component"
    )

    def __repr__(self):
        return f"<SalaryComponent(code='{self.code}', name='{self.name}')>"