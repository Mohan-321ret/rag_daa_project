"""Persist retrieved source chunks on tickets.

Revision ID: 003_ticket_sources
Revises: 002_ticket_infra
Create Date: 2026-09-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003_ticket_sources"
down_revision: Union[str, None] = "002_ticket_infra"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tickets")}
    if "source_chunks" not in columns:
        op.add_column("tickets", sa.Column("source_chunks", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tickets")}
    if "source_chunks" in columns:
        op.drop_column("tickets", "source_chunks")
