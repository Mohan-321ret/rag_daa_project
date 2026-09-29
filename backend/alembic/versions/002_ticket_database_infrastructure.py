"""Add ticket database infrastructure.

Revision ID: 002_ticket_database_infrastructure
Revises: 001_initial
Create Date: 2026-09-29
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "002_ticket_infra"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    return sa.inspect(op.get_bind())


def _has_foreign_key(table_name: str, columns: list[str], referred_table: str) -> bool:
    return any(
        fk["constrained_columns"] == columns and fk["referred_table"] == referred_table
        for fk in _inspector().get_foreign_keys(table_name)
    )


def upgrade() -> None:
    inspector = _inspector()
    if "tickets" not in inspector.get_table_names():
        raise RuntimeError("The tickets table must be initialized before this migration.")

    columns = {column["name"] for column in inspector.get_columns("tickets")}
    if "original_question" in columns and "user_query" not in columns:
        op.alter_column("tickets", "original_question", new_column_name="user_query")
    elif "original_question" in columns and "user_query" in columns:
        op.execute(
            "UPDATE tickets SET user_query = original_question "
            "WHERE user_query IS NULL"
        )

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "ticket_number" not in columns:
        op.add_column("tickets", sa.Column("ticket_number", sa.Integer(), nullable=True))

    op.execute("CREATE SEQUENCE IF NOT EXISTS tickets_ticket_number_seq")
    op.execute(
        "UPDATE tickets SET ticket_number = nextval('tickets_ticket_number_seq') "
        "WHERE ticket_number IS NULL"
    )
    op.execute("ALTER SEQUENCE tickets_ticket_number_seq OWNED BY tickets.ticket_number")
    op.execute(
        "ALTER TABLE tickets ALTER COLUMN ticket_number "
        "SET DEFAULT nextval('tickets_ticket_number_seq'::regclass)"
    )
    op.execute(
        "SELECT setval('tickets_ticket_number_seq', "
        "COALESCE(MAX(ticket_number), 1), MAX(ticket_number) IS NOT NULL) FROM tickets"
    )
    op.alter_column("tickets", "ticket_number", nullable=False)

    if not any(
        constraint.get("column_names") == ["ticket_number"]
        for constraint in _inspector().get_unique_constraints("tickets")
    ):
        op.create_unique_constraint(
            "uq_tickets_ticket_number", "tickets", ["ticket_number"]
        )

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "assigned_manager_id" not in columns:
        op.add_column(
            "tickets",
            sa.Column("assigned_manager_id", UUID(as_uuid=True), nullable=True),
        )
    if not _has_foreign_key("tickets", ["user_id"], "users"):
        op.create_foreign_key(
            "fk_tickets_user_id_users", "tickets", "users",
            ["user_id"], ["id"], ondelete="SET NULL",
        )
    if not _has_foreign_key("tickets", ["assigned_manager_id"], "users"):
        op.create_foreign_key(
            "fk_tickets_assigned_manager_id_users", "tickets", "users",
            ["assigned_manager_id"], ["id"], ondelete="SET NULL",
        )
    if not any(
        index["name"] == "ix_tickets_assigned_manager_id"
        for index in _inspector().get_indexes("tickets")
    ):
        op.create_index("ix_tickets_assigned_manager_id", "tickets", ["assigned_manager_id"])

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "resolution_format" not in columns:
        op.add_column(
            "tickets", sa.Column("resolution_format", sa.String(length=8), nullable=True)
        )
    if not any(
        check["name"] == "ck_tickets_resolution_format"
        for check in _inspector().get_check_constraints("tickets")
    ):
        op.create_check_constraint(
            "ck_tickets_resolution_format",
            "tickets",
            "resolution_format IS NULL OR resolution_format IN ('TEXT', 'FILE', 'BOTH')",
        )

    if "ticket_documents" not in _inspector().get_table_names():
        op.create_table(
            "ticket_documents",
            sa.Column("ticket_id", UUID(as_uuid=True), nullable=False),
            sa.Column("document_id", sa.String(length=64), nullable=False),
            sa.ForeignKeyConstraint(
                ["ticket_id"], ["tickets.id"],
                name="fk_ticket_documents_ticket_id_tickets", ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["document_id"], ["documents.document_id"],
                name="fk_ticket_documents_document_id_documents", ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("ticket_id", "document_id", name="pk_ticket_documents"),
        )


def downgrade() -> None:
    inspector = _inspector()
    if "ticket_documents" in inspector.get_table_names():
        op.drop_table("ticket_documents")

    if "tickets" not in _inspector().get_table_names():
        return

    check_names = {
        check["name"] for check in _inspector().get_check_constraints("tickets")
    }
    if "ck_tickets_resolution_format" in check_names:
        op.drop_constraint("ck_tickets_resolution_format", "tickets", type_="check")

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "resolution_format" in columns:
        op.drop_column("tickets", "resolution_format")

    foreign_keys = {
        fk["name"] for fk in _inspector().get_foreign_keys("tickets")
    }
    for name in ("fk_tickets_assigned_manager_id_users", "fk_tickets_user_id_users"):
        if name in foreign_keys:
            op.drop_constraint(name, "tickets", type_="foreignkey")

    indexes = {index["name"] for index in _inspector().get_indexes("tickets")}
    if "ix_tickets_assigned_manager_id" in indexes:
        op.drop_index("ix_tickets_assigned_manager_id", table_name="tickets")

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "assigned_manager_id" in columns:
        op.drop_column("tickets", "assigned_manager_id")

    unique_names = {
        constraint["name"]
        for constraint in _inspector().get_unique_constraints("tickets")
    }
    if "uq_tickets_ticket_number" in unique_names:
        op.drop_constraint("uq_tickets_ticket_number", "tickets", type_="unique")
    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "ticket_number" in columns:
        op.drop_column("tickets", "ticket_number")
    op.execute("DROP SEQUENCE IF EXISTS tickets_ticket_number_seq")

    columns = {column["name"] for column in _inspector().get_columns("tickets")}
    if "user_query" in columns and "original_question" not in columns:
        op.alter_column("tickets", "user_query", new_column_name="original_question")