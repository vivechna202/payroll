import uuid

from sqlalchemy import (
    Column,
    ForeignKey,
    Numeric,
    DateTime
)

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base
from sqlalchemy import UniqueConstraint

class StructureComponent(Base):
    __tablename__ = "structure_components"

    __table_args__ = (
        UniqueConstraint(
             "structure_id",
              "component_id",
              name="uq_structure_component"
      ),
    )
    
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )

    structure_id = Column(
        UUID(as_uuid=True),
        ForeignKey("salary_structures.structure_id", ondelete="CASCADE"),
        nullable=False
    )

    component_id = Column(
        UUID(as_uuid=True),
        ForeignKey("salary_components.component_id", ondelete="CASCADE"),
        nullable=False
    )

    override_amount = Column(
        Numeric(12, 2),
        nullable=True
    )

    override_percentage = Column(
        Numeric(5, 2),
        nullable=True
    )

    added_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relationships
    salary_structure = relationship(
        "SalaryStructure",
        back_populates="structure_components"
    )

    salary_component = relationship(
        "SalaryComponent",
        back_populates="structure_components"
    )

    def __repr__(self):
        return (
            f"<StructureComponent("
            f"structure_id={self.structure_id}, "
            f"component_id={self.component_id})>"
        )