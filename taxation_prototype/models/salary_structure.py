import uuid

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    DateTime
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base


class SalaryStructure(Base):
    __tablename__ = "salary_structures"

    structure_id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    name = Column(
        String(100),
        nullable=False,
        unique=True
    )

    structure_type = Column(
        String(50),
        nullable=False
    )

    payroll_frequency = Column(
        String(30),
        nullable=False
    )

    description = Column(
        Text,
        nullable=True
    )

    active = Column(
        Boolean,
        default=True,
        nullable=False
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

    # Relationships
    structure_components = relationship(
        "StructureComponent",
        back_populates="salary_structure",
        cascade="all, delete-orphan"
    )

    employee_salaries = relationship(
        "EmployeeSalary",
        back_populates="salary_structure"
    )

    def __repr__(self):
        return f"<SalaryStructure(name='{self.name}')>"