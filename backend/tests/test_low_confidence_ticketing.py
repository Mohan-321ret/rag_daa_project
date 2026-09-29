import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest

from app.core.permissions import Role
from app.api import rag as rag_api
from app.models.document import Document
from app.models.schemas import RAGQueryRequest
from app.models.ticket import Ticket, TicketStatus
from app.services import rag_service, ticket_service


class FakeQuery:
    def __init__(self, result=None, rows=None):
        self.result = result
        self.rows = rows or []

    def filter(self, *args):
        return self

    def first(self):
        return self.result

    def all(self):
        return self.rows


class FakeDatabase:
    def __init__(self, ticket_results=None, documents=None):
        self.ticket_results = list(ticket_results or [])
        self.documents = list(documents or [])
        self.added = []

    def query(self, model):
        if model is Ticket:
            result = self.ticket_results.pop(0) if self.ticket_results else None
            return FakeQuery(result=result)
        if model is Document:
            return FakeQuery(rows=self.documents)
        raise AssertionError(f"Unexpected model queried: {model}")

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass

    def commit(self):
        pass

    def refresh(self, row):
        pass

    def rollback(self):
        pass


def _run_rag_query(monkeypatch, confidence, index_total=1):
    user_id = uuid.uuid4()
    user = SimpleNamespace(id=user_id, email="employee@example.com")
    chunk = {
        "document_id": "DOC_FINANCE_1",
        "chunk_index": 3,
        "text": "Expense approvals require manager review.",
        "score": 0.18,
        "metadata": {"document_id": "DOC_FINANCE_1", "chunk_index": 3},
        "source": "vector",
    }
    analysis = SimpleNamespace(
        intent=SimpleNamespace(intent="fact"),
        complexity=SimpleNamespace(level="simple"),
        entities=[],
        normalized_query="What is the approval process?",
        suggested_top_k=5,
    )
    route = SimpleNamespace(route="vector", signals=[], reason="fact lookup")
    retrieval = SimpleNamespace(route=route, results=[chunk])
    fusion = SimpleNamespace(
        prompt=SimpleNamespace(optimized_context="source context"),
        results=[chunk],
        stats={},
    )
    ticket = SimpleNamespace(
        id=uuid.uuid4(), ticket_id="TKT_TEST", domain="finance",
        department="finance", status="open"
    )
    created = {}
    score_calls = []

    async def analyze_query(*args, **kwargs):
        return analysis

    async def generate_answer(*args, **kwargs):
        return SimpleNamespace(
            answer="Manager approval is required.",
            model_used="test-model",
            provider="test-provider",
            grounding=SimpleNamespace(is_grounded=True),
        )

    def calculate_confidence(chunks):
        score_calls.append(chunks)
        return confidence

    def create_ticket(_db, **kwargs):
        created.update(kwargs)
        return ticket, "A review ticket has been created."

    monkeypatch.setattr(rag_service, "build_chunk_access_context", lambda *args: object())
    monkeypatch.setattr(rag_service, "analyze_query", analyze_query)
    monkeypatch.setattr(
        rag_service, "get_vector_store", lambda: SimpleNamespace(total=index_total)
    )
    monkeypatch.setattr(rag_service, "adaptive_retrieve", lambda *args, **kwargs: retrieval)
    monkeypatch.setattr(rag_service, "fuse_context", lambda *args, **kwargs: fusion)
    monkeypatch.setattr(rag_service, "generate_answer", generate_answer)
    monkeypatch.setattr(rag_service, "calculate_retrieval_confidence", calculate_confidence)
    monkeypatch.setattr(rag_service.settings, "verification_enabled", False)
    monkeypatch.setattr(rag_service.settings, "query_logging_enabled", False)
    monkeypatch.setattr(ticket_service, "get_ticket_confidence_threshold", lambda db: 0.2)
    monkeypatch.setattr(ticket_service, "is_ticketing_enabled", lambda db: True)
    monkeypatch.setattr(ticket_service, "create_ticket_from_low_confidence", create_ticket)

    response = asyncio.run(
        rag_service.answer_question(
            db=object(),
            query=analysis.normalized_query,
            current_user=user,
            caller_role=Role.ANALYST,
        )
    )
    return response, created, score_calls, user_id


def test_rag_at_threshold_returns_normal_response_without_ticket(monkeypatch):
    response, created, score_calls, _ = _run_rag_query(monkeypatch, 0.2)

    assert response["answer"] == "Manager approval is required."
    assert response["confidence_score"] == 0.2
    assert response["ticket"] is None
    assert created == {}
    assert len(score_calls) == 1


def test_rag_below_threshold_returns_answer_and_creates_ticket(monkeypatch):
    response, created, score_calls, user_id = _run_rag_query(monkeypatch, 0.19)

    assert response["answer"] == "Manager approval is required."
    assert response["confidence_score"] == 0.19
    assert response["ticket"]["ticket_id"] == "TKT_TEST"
    assert created["user_id"] == str(user_id)
    assert created["original_question"] == "What is the approval process?"
    assert created["confidence_score"] == 0.19
    assert created["source_document_ids"] == ["DOC_FINANCE_1"]
    assert created["source_chunks"][0]["chunk_index"] == 3
    assert len(score_calls) == 1


def test_empty_knowledge_base_creates_ticket_and_returns_explanation(monkeypatch):
    response, created, score_calls, user_id = _run_rag_query(
        monkeypatch, 0.0, index_total=0
    )

    assert response["confidence_score"] == 0.0
    assert response["answer"].startswith("The knowledge base is empty.")
    assert response["ticket"]["status"] == "open"
    assert created["user_id"] == str(user_id)
    assert created["confidence_score"] == 0.0
    assert created["preserve_open_status"] is True
    assert score_calls == []


def test_ticket_persists_user_confidence_domain_and_sources(monkeypatch):
    user_id = uuid.uuid4()
    document = Document(
        document_id="DOC_FINANCE_1",
        filename="finance.txt",
        original_filename="finance.txt",
        document_type="TXT",
        file_extension=".txt",
    )
    db = FakeDatabase(ticket_results=[None, None], documents=[document])
    monkeypatch.setattr(ticket_service.settings, "domain_routing_enabled", False)
    monkeypatch.setattr(ticket_service, "is_ticketing_enabled", lambda db: True)
    monkeypatch.setattr(ticket_service, "_emit_ticket_created_signal", lambda **kwargs: None)

    ticket, _ = ticket_service.create_ticket_from_low_confidence(
        db=db,
        query_id="QRY_LOW_CONFIDENCE_TEST",
        user_id=str(user_id),
        original_question="What is the approval process?",
        generated_answer="Manager approval is required.",
        confidence_score=0.19,
        confidence_threshold=0.2,
        domain="finance",
        source_document_ids=["DOC_FINANCE_1"],
        source_chunks=[
            {
                "document_id": "DOC_FINANCE_1",
                "chunk_index": 3,
                "score": 0.18,
                "text_preview": "Manager review is required.",
            }
        ],
    )

    assert ticket is db.added[0]
    assert str(ticket.user_id) == str(user_id)
    assert ticket.confidence_score == 0.19
    assert ticket.domain == "finance"
    assert ticket.status == TicketStatus.OPEN.value
    assert json.loads(ticket.source_document_ids) == ["DOC_FINANCE_1"]
    assert json.loads(ticket.source_chunks)[0]["chunk_index"] == 3
    assert ticket.documents == [document]


def test_same_query_id_returns_existing_ticket_without_duplicate(monkeypatch):
    existing = SimpleNamespace(occurrence_count=1)
    db = FakeDatabase(ticket_results=[existing])
    monkeypatch.setattr(ticket_service, "is_ticketing_enabled", lambda db: True)

    ticket, _ = ticket_service.create_ticket_from_low_confidence(
        db=db,
        query_id="QRY_RETRY_TEST",
        user_id=str(uuid.uuid4()),
        original_question="Retry this request",
        generated_answer="Answer",
        confidence_score=0.1,
        confidence_threshold=0.2,
    )

    assert ticket is existing
    assert db.added == []
    assert existing.occurrence_count == 1


def test_rag_api_shares_request_id_with_service(monkeypatch):
    captured = {}

    async def answer_question(**kwargs):
        captured.update(kwargs)
        return {
            "query": kwargs["query"],
            "query_id": kwargs["query_id"],
            "answer": "Answer",
            "sources": [],
            "retrieved_chunks": 0,
            "total_indexed": 0,
            "confidence_score": 0.2,
            "ticket": None,
        }

    monkeypatch.setattr(rag_api, "answer_question", answer_question)
    monkeypatch.setattr(rag_api, "log_query", lambda **kwargs: None)
    response = asyncio.run(
        rag_api.rag_query(
            body=RAGQueryRequest(question="What is the approval process?"),
            db=object(),
            current_user=SimpleNamespace(
                id=uuid.uuid4(), email="employee@example.com", department="Finance"
            ),
            caller_role=Role.ANALYST,
        )
    )

    assert captured["query_id"] == response.query_id
    assert captured["write_query_log"] is False
