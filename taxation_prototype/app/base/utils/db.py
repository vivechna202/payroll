"""Shared database utilities (SQLAlchemy base + engine)."""
from sqlalchemy.orm import declarative_base

Base = declarative_base()

from sqlalchemy import create_engine

DATABASE_URL = "postgresql+psycopg2://hrms_user:hrms123@localhost:5432/hrms_db"

engine = create_engine(
    DATABASE_URL,
    echo=True
)
