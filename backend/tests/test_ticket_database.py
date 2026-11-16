from sqlalchemy.orm import configure_mappers

from app.models import chunk, document, domain, ticket, user
from app.models.ticket import RESOLUTION_FORMATS, TicketStatus


def test_ticket_database_contract():
    configure_mappers()

    required_columns = {
        "ticket_id",
        "ticket_number",
        "user_id",
        "user_query",
        "generated_answer",
        "confidence_score",
        "domain",
        "assigned_manager_id",
        "status",
        "priority",
        "resolution",
        "resolution_type",
        "created_at",
        "updated_at",
        "resolved_at",
    }
    assert required_columns <= set(ticket.Ticket.__table__.columns.keys())
    assert RESOLUTION_FORMATS == ["TEXT", "FILE", "BOTH"]
    assert TicketStatus.REOPENED.value == "reopened"
    assert ticket.Ticket.original_question.property.columns[0].name == "user_query"
    assert {"user", "assigned_manager", "routed_domain", "documents"} <= set(
        ticket.Ticket.__mapper__.relationships.keys()
    )
    assert {"ticket_id", "document_id"} == set(ticket.ticket_documents.columns.keys())
