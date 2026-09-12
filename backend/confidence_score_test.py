"""
Confidence Score Test Suite
---------------------------
Tests the deterministic retrieval confidence score implementation:
  1. High confidence case (score >= 0.80 -> High)
  2. Medium confidence case (0.60 <= score < 0.80 -> Medium)
  3. Low confidence case (score < 0.60 -> Low)
  4. No-result case (empty chunks -> score == 0.0)
  5. Score range normalization (0.0 to 1.0)
  6. Configurable threshold checking (CONFIDENCE_THRESHOLD=0.70)
  7. API Response schema verification (confidence_score in RAGQueryResponse)
"""
import pytest
from app.services.confidence_service import (
    calculate_retrieval_confidence,
    get_confidence_level,
    normalize_similarity_score,
    CONFIDENCE_THRESHOLD,
)
from app.models.schemas import RAGQueryResponse, RAGSource


def test_normalize_similarity_score():
    # Vector cosine similarity
    assert normalize_similarity_score(0.85, "vector") == 0.85
    assert normalize_similarity_score(1.5, "vector") == 1.0
    assert normalize_similarity_score(-0.2, "vector") == 0.0

    # BM25 score saturation
    assert normalize_similarity_score(0.0, "bm25") == 0.0
    assert 0.4 < normalize_similarity_score(10.0, "bm25") < 0.6

    # Graph score
    assert normalize_similarity_score(0.5, "graph") == 0.5

    # Hybrid RRF score
    assert normalize_similarity_score(0.04, "hybrid") == 0.8


def test_no_result_case():
    """No retrieved chunks should produce 0.0 confidence."""
    confidence = calculate_retrieval_confidence([])
    assert confidence == 0.0
    assert get_confidence_level(confidence) == "Low"


def test_high_confidence_case():
    """Chunks with high similarity (>= 0.80) produce High confidence (>= 0.80 / 80%+)."""
    high_chunks = [
        {"score": 0.95, "source": "vector"},
        {"score": 0.88, "source": "vector"},
        {"score": 0.82, "source": "vector"},
    ]
    confidence = calculate_retrieval_confidence(high_chunks)
    assert 0.80 <= confidence <= 1.0
    assert get_confidence_level(confidence) == "High"


def test_medium_confidence_case():
    """Chunks with moderate similarity (0.60–0.79) produce Medium confidence."""
    medium_chunks = [
        {"score": 0.72, "source": "vector"},
        {"score": 0.68, "source": "vector"},
        {"score": 0.65, "source": "vector"},
    ]
    confidence = calculate_retrieval_confidence(medium_chunks)
    assert 0.60 <= confidence < 0.80
    assert get_confidence_level(confidence) == "Medium"


def test_low_confidence_case():
    """Chunks with weak similarity (< 0.60) produce Low confidence."""
    low_chunks = [
        {"score": 0.45, "source": "vector"},
        {"score": 0.38, "source": "vector"},
        {"score": 0.30, "source": "vector"},
    ]
    confidence = calculate_retrieval_confidence(low_chunks)
    assert confidence < 0.60
    assert get_confidence_level(confidence) == "Low"


def test_confidence_threshold_config():
    """Verify configurable threshold constant."""
    assert CONFIDENCE_THRESHOLD == 0.70


def test_schema_includes_confidence_score():
    """Verify RAGQueryResponse schema supports confidence_score."""
    response = RAGQueryResponse(
        query="What is the leave policy?",
        answer="Employees get 25 days annual leave.",
        sources=[RAGSource(document_id="DOC_001", chunk_index=0, score=0.89, text_preview="Leave policy...")],
        retrieved_chunks=1,
        total_indexed=10,
        provider="system",
        confidence_score=0.8850,
    )
    assert response.confidence_score == 0.8850


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
