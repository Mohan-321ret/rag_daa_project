"""
SQLAlchemy declarative base and database initialization helpers.
All ORM models import Base from this module.
"""
from __future__ import annotations

from app.db.database import Base, engine  # noqa: F401 – re-export for models


def init_db() -> None:
    """Create all tables that don't yet exist in the database."""
    # Import all models so SQLAlchemy registers them against Base.metadata
    from app.models import document  # noqa: F401
    Base.metadata.create_all(bind=engine)
