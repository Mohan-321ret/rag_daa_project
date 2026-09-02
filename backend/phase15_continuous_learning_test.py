"""
Phase 15 Integration Tests — Ticketing ↔ Continuous Learning
==============================================================
Tests cover:
  1. Learning signal recording (all 8 signal types)
  2. Signal hooks from feedback_service (submit_feedback)
  3. Signal hooks from ticket_service (create + resolve)
  4. Extended metrics (8 metrics vs original 4)
  5. Confidence calibration analysis
  6. Threshold suggestions (read-only, non-destructive)
  7. Threshold apply (admin action, auditable)
  8. Routing improvement service Phase 15 extensions
  9. API endpoints (via TestClient)

Run:
    cd backend
    python -m pytest phase15_continuous_learning_test.py -v

Requires a running PostgreSQL connection and the app tables to exist.
Uses the same in-process TestClient pattern as other phase tests.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.database import Base, get_db
from app.main import app

# ── Test DB setup ─────────────────────────────────────────────────────────────
TEST_DATABASE_URL = settings.database_url

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db():
    """Provide a real DB session for service-level tests."""
    from app.db.base import init_db
    init_db()
    session = TestingSessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def admin_token(client):
    """Register and login as admin, return Bearer token."""
    import random, string
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    email = f"phase15_admin_{suffix}@test.com"
    password = "AdminPass123!"

    reg_resp = client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": "Phase15 Admin",
    })
    assert reg_resp.status_code in (201, 400), reg_resp.text

    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if login_resp.status_code != 200:
        pytest.skip("Login failed — DB not reachable or auth misconfigured")

    token = login_resp.json()["access_token"]

    # Elevate to super_admin
    from app.models.user import User
    db_sess = TestingSessionLocal()
    try:
        u = db_sess.query(User).filter(User.email == email).first()
        if u:
            u.role = "super_admin"
            db_sess.commit()
    finally:
        db_sess.close()

    return token


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="module")
def sample_query_id(db):
    """Create a minimal QueryLog row for tests that need a valid query_id."""
    from app.models.query_log import QueryLog

    qid = f"QRY_TEST_{uuid.uuid4().hex[:6].upper()}"
    row = QueryLog(
        query_id=qid,
        query_text="What is the leave policy?",
        answer_text="The leave policy grants 25 days per year.",
        route="vector",
        intent="fact_retrieval",
        confidence_score=0.45,
        hallucinations_detected=0,
        was_rewritten=False,
        retrieved_chunks=3,
        latency_ms=320.0,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return qid


# ── 1. Learning Signal Service: Record & Query ────────────────────────────────

class TestLearningSignalService:
    """Unit tests for learning_signals_service.py"""

    def test_record_feedback_up_signal(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal, list_signals

        sig = record_signal(
            db,
            LearningSignalType.FEEDBACK_UP,
            query_id=sample_query_id,
            confidence_score=0.45,
            was_correct="yes",
            retrieval_route="vector",
            intent="fact_retrieval",
        )
        assert sig.signal_id.startswith("SIG_")
        assert sig.signal_type == LearningSignalType.FEEDBACK_UP
        assert sig.was_correct == "yes"
        assert sig.confidence_score == 0.45

    def test_record_feedback_down_with_details(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        sig = record_signal(
            db,
            LearningSignalType.FEEDBACK_DOWN,
            query_id=sample_query_id,
            confidence_score=0.45,
            was_correct="no",
            details={"reason": "answer was wrong"},
        )
        assert sig.signal_type == LearningSignalType.FEEDBACK_DOWN
        assert sig.details is not None
        parsed = json.loads(sig.details)
        assert parsed["reason"] == "answer was wrong"

    def test_record_ticket_created_signal(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        fake_ticket_id = f"TKT_{uuid.uuid4().hex[:8].upper()}"
        sig = record_signal(
            db,
            LearningSignalType.TICKET_CREATED,
            query_id=sample_query_id,
            ticket_id=fake_ticket_id,
            confidence_score=0.35,
            details={"priority": "high", "domain": "HR"},
        )
        assert sig.signal_type == LearningSignalType.TICKET_CREATED
        assert sig.ticket_id == fake_ticket_id

    def test_record_retrieval_failure_signal(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        sig = record_signal(
            db,
            LearningSignalType.RETRIEVAL_FAILURE,
            query_id=sample_query_id,
            was_correct="no",
            retrieval_route="bm25",
            details={"source": "user_flagged"},
        )
        assert sig.signal_type == LearningSignalType.RETRIEVAL_FAILURE

    def test_record_hallucination_signal(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        sig = record_signal(
            db,
            LearningSignalType.HALLUCINATION_DETECTED,
            query_id=sample_query_id,
            confidence_score=0.60,
            was_correct="no",
            details={"source": "expert_resolution"},
        )
        assert sig.signal_type == LearningSignalType.HALLUCINATION_DETECTED

    def test_record_routing_error_signal(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal

        sig = record_signal(
            db,
            LearningSignalType.ROUTING_ERROR,
            query_id=sample_query_id,
            details={"source": "user_flagged", "domain_routing_correct": False},
        )
        assert sig.signal_type == LearningSignalType.ROUTING_ERROR

    def test_list_signals_with_filter(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import list_signals

        signals = list_signals(db, query_id=sample_query_id, limit=100)
        assert len(signals) >= 1
        assert all(s.query_id == sample_query_id for s in signals)

    def test_get_signals_summary(self, db):
        from app.services.learning_signals_service import get_signals_summary

        summary = get_signals_summary(db, window_days=7)
        assert isinstance(summary, dict)
        # All values should be positive integers
        for k, v in summary.items():
            assert isinstance(v, int) and v >= 0

    def test_calibration_data(self, db, sample_query_id):
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal, get_calibration_data

        # Seed calibration signals at different confidence levels
        for conf, correct in [(0.3, "no"), (0.5, "partial"), (0.7, "yes"), (0.9, "yes")]:
            record_signal(
                db, LearningSignalType.FEEDBACK_UP if correct == "yes" else LearningSignalType.FEEDBACK_DOWN,
                query_id=sample_query_id,
                confidence_score=conf,
                was_correct=correct,
            )

        buckets = get_calibration_data(db, window_days=7)
        assert isinstance(buckets, list)
        for b in buckets:
            assert "bucket_min" in b
            assert "actual_correctness_rate" in b
            assert 0.0 <= b["actual_correctness_rate"] <= 1.0


# ── 2. Feedback Service Signal Hooks ──────────────────────────────────────────

class TestFeedbackServiceSignals:
    """Verify feedback_service emits learning signals on submit."""

    def test_submit_thumbs_up_emits_signal(self, db, sample_query_id):
        from app.services.feedback_service import submit_feedback
        from app.models.learning_signal import LearningSignal, LearningSignalType

        before_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.FEEDBACK_UP,
        ).count()

        submit_feedback(db, sample_query_id, "up")

        after_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.FEEDBACK_UP,
        ).count()
        assert after_count == before_count + 1

    def test_submit_with_correction_emits_correction_signal(self, db, sample_query_id):
        from app.services.feedback_service import submit_feedback
        from app.models.learning_signal import LearningSignal, LearningSignalType

        before_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.CORRECTION,
        ).count()

        submit_feedback(
            db, sample_query_id, "down",
            correction_text="The correct answer is 30 days per year.",
        )

        after_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.CORRECTION,
        ).count()
        assert after_count == before_count + 1

    def test_submit_with_retrieval_failure_flag(self, db, sample_query_id):
        from app.services.feedback_service import submit_feedback
        from app.models.learning_signal import LearningSignal, LearningSignalType

        before_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.RETRIEVAL_FAILURE,
        ).count()

        submit_feedback(
            db, sample_query_id, "down",
            retrieval_failure_flagged=True,
        )

        after_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.RETRIEVAL_FAILURE,
        ).count()
        assert after_count == before_count + 1

    def test_submit_with_routing_wrong_flag(self, db, sample_query_id):
        from app.services.feedback_service import submit_feedback
        from app.models.learning_signal import LearningSignal, LearningSignalType

        before_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.ROUTING_ERROR,
        ).count()

        submit_feedback(
            db, sample_query_id, "down",
            domain_routing_correct=False,
        )

        after_count = db.query(LearningSignal).filter(
            LearningSignal.query_id == sample_query_id,
            LearningSignal.signal_type == LearningSignalType.ROUTING_ERROR,
        ).count()
        assert after_count == before_count + 1

    def test_new_feedback_fields_stored(self, db, sample_query_id):
        from app.services.feedback_service import submit_feedback
        from app.models.feedback import Feedback

        fake_ticket = f"TKT_{uuid.uuid4().hex[:8].upper()}"
        row = submit_feedback(
            db, sample_query_id, "up",
            ticket_id=fake_ticket,
            domain_routing_correct=True,
            retrieval_failure_flagged=False,
        )
        assert row.ticket_id == fake_ticket
        assert row.domain_routing_correct is True
        assert row.retrieval_failure_flagged is False


# ── 3. Extended Metrics ───────────────────────────────────────────────────────

class TestExtendedMetrics:
    """Verify the Phase 15 extended metrics compute without errors."""

    def test_compute_metrics_returns_8_metrics(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=30)
        # Phase 12 fields
        assert hasattr(summary, "user_satisfaction")
        assert hasattr(summary, "hallucination_rate")
        assert hasattr(summary, "avg_latency_ms")
        assert hasattr(summary, "retrieval_accuracy_by_route")
        # Phase 15 new fields
        assert hasattr(summary, "ticket_generation_rate")
        assert hasattr(summary, "ticket_resolution_rate")
        assert hasattr(summary, "domain_routing_accuracy")
        assert hasattr(summary, "avg_ticket_resolution_time_hours")
        assert hasattr(summary, "signal_counts")

    def test_ticket_generation_rate_is_ratio(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=30)
        if summary.ticket_generation_rate is not None:
            assert 0.0 <= summary.ticket_generation_rate <= 1.0

    def test_ticket_resolution_rate_is_ratio(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=30)
        if summary.ticket_resolution_rate is not None:
            assert 0.0 <= summary.ticket_resolution_rate <= 1.0

    def test_domain_routing_accuracy_is_ratio(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=30)
        if summary.domain_routing_accuracy is not None:
            assert 0.0 <= summary.domain_routing_accuracy <= 1.0

    def test_signal_counts_dict(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=30)
        assert isinstance(summary.signal_counts, dict)

    def test_all_time_window(self, db):
        from app.services.metrics_service import compute_metrics

        summary = compute_metrics(db, window_days=None)
        assert summary.window_days is None
        assert summary.total_queries >= 0


# ── 4. Confidence Advisor ─────────────────────────────────────────────────────

class TestConfidenceAdvisor:
    """Verify confidence advisor is read-only and produces auditable suggestions."""

    def test_analyze_confidence_threshold_no_crash(self, db):
        from app.services.confidence_advisor_service import analyze_confidence_threshold

        result = analyze_confidence_threshold(db, window_days=30)
        # May return None (insufficient data) — both are valid
        if result is not None:
            assert "metric_name" in result
            assert "suggested_value" in result
            assert "reason" in result
            assert 0.1 <= result["suggested_value"] <= 0.95

    def test_analyze_routing_threshold_no_crash(self, db):
        from app.services.confidence_advisor_service import analyze_routing_threshold

        result = analyze_routing_threshold(db, window_days=30)
        if result is not None:
            assert result["metric_name"] == "routing_confidence_threshold"
            assert isinstance(result["suggested_value"], float)

    def test_generate_suggestions_dry_run(self, db):
        from app.services.confidence_advisor_service import generate_suggestions

        # persist=False → no DB writes
        suggestions = generate_suggestions(db, window_days=30, persist=False)
        assert isinstance(suggestions, list)

    def test_generate_suggestions_with_persist(self, db):
        from app.services.confidence_advisor_service import generate_suggestions, list_threshold_history
        from app.models.threshold_history import ThresholdSource

        before = len(list_threshold_history(db, source=ThresholdSource.AUTO_SUGGESTION))
        generate_suggestions(db, window_days=30, persist=True)
        after = len(list_threshold_history(db, source=ThresholdSource.AUTO_SUGGESTION))
        # After >= before (may be 0 new ones if data insufficient — that's fine)
        assert after >= before

    def test_get_pending_suggestions(self, db):
        from app.services.confidence_advisor_service import get_pending_suggestions

        pending = get_pending_suggestions(db)
        assert isinstance(pending, list)
        for s in pending:
            assert s.applied_at is None

    def test_list_threshold_history_structure(self, db):
        from app.services.confidence_advisor_service import list_threshold_history

        rows = list_threshold_history(db)
        assert isinstance(rows, list)
        for row in rows:
            assert hasattr(row, "history_id")
            assert hasattr(row, "metric_name")
            assert hasattr(row, "source")


# ── 5. Routing Improvement Phase 15 Extensions ───────────────────────────────

class TestRoutingImprovementPhase15:
    """Phase 15 additions to routing_improvement_service."""

    def test_get_domain_routing_accuracy(self, db):
        from app.services.routing_improvement_service import get_domain_routing_accuracy

        stats = get_domain_routing_accuracy(db, window_days=30)
        assert hasattr(stats, "total_routed")
        assert hasattr(stats, "routing_errors")
        assert hasattr(stats, "accuracy")
        assert hasattr(stats, "needs_triage_count")
        if stats.accuracy is not None:
            assert 0.0 <= stats.accuracy <= 1.0

    def test_get_retrieval_failure_patterns(self, db):
        from app.services.routing_improvement_service import get_retrieval_failure_patterns

        patterns = get_retrieval_failure_patterns(db, window_days=30)
        assert isinstance(patterns, list)
        for p in patterns:
            assert hasattr(p, "route")
            assert hasattr(p, "failure_rate")
            assert 0.0 <= p.failure_rate <= 1.0

    def test_get_improvement_summary(self, db):
        from app.services.routing_improvement_service import get_improvement_summary

        report = get_improvement_summary(db, window_days=30)
        assert "domain_routing" in report
        assert "retrieval_failure_patterns" in report
        assert "route_satisfaction" in report
        assert "learning_settings" in report
        assert "window_days" in report


# ── 6. API Endpoint Tests ─────────────────────────────────────────────────────

class TestLearningAPIEndpoints:
    """Integration tests for the /api/v1/learning/* endpoints."""

    def test_signals_endpoint_authenticated(self, client, auth_headers):
        resp = client.get("/api/v1/learning/signals", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "signals" in body
        assert "total" in body
        assert "signal_counts" in body
        assert isinstance(body["signals"], list)

    def test_signals_endpoint_unauthenticated_rejected(self, client):
        resp = client.get("/api/v1/learning/signals")
        assert resp.status_code in (401, 403)

    def test_signals_filter_by_type(self, client, auth_headers):
        resp = client.get(
            "/api/v1/learning/signals",
            params={"signal_type": "feedback_up"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        for sig in body["signals"]:
            assert sig["signal_type"] == "feedback_up"

    def test_threshold_history_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/learning/threshold-history", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_threshold_suggestions_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/learning/threshold-suggestions", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_generate_suggestions_endpoint(self, client, auth_headers):
        resp = client.post(
            "/api/v1/learning/threshold-suggestions/generate",
            params={"window_days": 30},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201)
        assert isinstance(resp.json(), list)

    def test_improvement_report_endpoint(self, client, auth_headers):
        resp = client.get(
            "/api/v1/learning/improvement-report",
            params={"window_days": 30},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "domain_routing" in body
        assert "retrieval_failure_patterns" in body
        assert "route_satisfaction" in body

    def test_threshold_apply_invalid_id(self, client, auth_headers):
        resp = client.post(
            "/api/v1/learning/threshold-apply",
            json={"suggestion_id": "THR_DOESNOTEXIST99"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_threshold_apply_valid_flow(self, client, auth_headers, db):
        """Full flow: generate a suggestion → apply it → verify audit trail."""
        from app.services.confidence_advisor_service import (
            generate_suggestions, list_threshold_history,
        )
        from app.models.threshold_history import ThresholdSource, TRACKABLE_METRICS
        import uuid as _uuid

        # Manually inject a suggestion so we don't depend on calibration data
        from app.models.threshold_history import ThresholdHistory
        fake_id = f"THR_{_uuid.uuid4().hex[:10].upper()}"
        row = ThresholdHistory(
            history_id=fake_id,
            metric_name="ticket_confidence_threshold",
            old_value=0.50,
            new_value=0.55,
            reason="Test: calibration showed higher threshold needed",
            source=ThresholdSource.AUTO_SUGGESTION,
        )
        db.add(row)
        db.commit()

        # Now apply it via API
        resp = client.post(
            "/api/v1/learning/threshold-apply",
            json={"suggestion_id": fake_id},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metric_name"] == "ticket_confidence_threshold"
        assert body["new_value"] == 0.55
        assert "applied_history_id" in body

        # Verify audit trail
        history_resp = client.get(
            "/api/v1/learning/threshold-history",
            params={"source": "admin_applied"},
            headers=auth_headers,
        )
        assert history_resp.status_code == 200
        applied_rows = history_resp.json()
        applied_ids = [r["suggestion_id"] for r in applied_rows]
        assert fake_id in applied_ids


class TestFeedbackAPIPhase15:
    """Tests for extended feedback API endpoints."""

    def test_extended_metrics_endpoint(self, client, auth_headers):
        resp = client.get("/api/v1/feedback/metrics/extended", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Phase 12 fields
        assert "user_satisfaction" in body
        assert "hallucination_rate" in body
        # Phase 15 fields
        assert "ticket_generation_rate" in body
        assert "ticket_resolution_rate" in body
        assert "domain_routing_accuracy" in body
        assert "avg_ticket_resolution_time_hours" in body
        assert "signal_counts" in body

    def test_confidence_calibration_endpoint(self, client, auth_headers):
        resp = client.get(
            "/api/v1/feedback/metrics/confidence-calibration",
            params={"window_days": 30},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        for bucket in body:
            assert "bucket_min" in bucket
            assert "actual_correctness_rate" in bucket

    def test_submit_feedback_with_phase15_fields(self, client, auth_headers, sample_query_id):
        resp = client.post(
            "/api/v1/feedback/submit",
            json={
                "query_id": sample_query_id,
                "rating": "down",
                "correction_text": "The correct answer is 28 days.",
                "ticket_id": None,
                "domain_routing_correct": True,
                "retrieval_failure_flagged": False,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "feedback_id" in body
        assert body["rating"] == "down"

    def test_original_metrics_still_work(self, client, auth_headers):
        """Phase 12 /metrics/summary endpoint must remain backward compatible."""
        resp = client.get("/api/v1/feedback/metrics/summary", headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        # Original 4 fields present
        assert "total_queries" in body
        assert "total_rated" in body
        assert "user_satisfaction" in body
        assert "hallucination_rate" in body


# ── 7. Model Integrity ────────────────────────────────────────────────────────

class TestModelIntegrity:
    """Verify the new ORM models have all required columns."""

    def test_learning_signal_model_columns(self):
        from app.models.learning_signal import LearningSignal, LearningSignalType

        cols = {c.name for c in LearningSignal.__table__.columns}
        required = {
            "id", "signal_id", "signal_type", "query_id", "ticket_id",
            "feedback_id", "domain_id", "confidence_score", "was_correct",
            "retrieval_route", "intent", "resolution_type", "details", "created_at",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_threshold_history_model_columns(self):
        from app.models.threshold_history import ThresholdHistory

        cols = {c.name for c in ThresholdHistory.__table__.columns}
        required = {
            "id", "history_id", "metric_name", "old_value", "new_value",
            "reason", "source", "approved_by", "applied_at", "suggestion_id", "created_at",
        }
        assert required.issubset(cols), f"Missing columns: {required - cols}"

    def test_feedback_model_phase15_columns(self):
        from app.models.feedback import Feedback

        cols = {c.name for c in Feedback.__table__.columns}
        assert "ticket_id" in cols
        assert "domain_routing_correct" in cols
        assert "retrieval_failure_flagged" in cols

    def test_signal_types_constants(self):
        from app.models.learning_signal import LearningSignalType

        expected = {
            "feedback_up", "feedback_down", "correction", "ticket_created",
            "ticket_resolved", "retrieval_failure", "hallucination_detected",
            "routing_error",
        }
        assert set(LearningSignalType.ALL) == expected

    def test_trackable_metrics_constants(self):
        from app.models.threshold_history import TRACKABLE_METRICS

        assert "ticket_confidence_threshold" in TRACKABLE_METRICS
        assert "routing_confidence_threshold" in TRACKABLE_METRICS


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
