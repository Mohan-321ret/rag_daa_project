"""Set the initial low-confidence ticket threshold to 0.2.

Revision ID: 004_ticket_threshold_02
Revises: 003_ticket_sources
Create Date: 2026-09-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004_ticket_threshold_02"
down_revision: Union[str, None] = "003_ticket_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "system_settings" in inspector.get_table_names():
        op.execute(
            "UPDATE system_settings SET value = '0.2', updated_at = now() "
            "WHERE key = 'ticket_confidence_threshold'"
        )


def downgrade() -> None:
    pass
