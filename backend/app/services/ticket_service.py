"""
Ticket Service  –  Phase 10, 11, 12: Enterprise Ticketing System & Admin Management
-----------------------------------------------------------------------------------
Handles ticket lifecycle management, dynamic threshold configuration, automatic
generation on low-confidence answers, multi-attribute filtering, Admin Dashboard analytics,
rich ticket details with QueryLog context, and domain-scoped administrative mutations.

Key functions:
- get_ticket_confidence_threshold(): Get active threshold from DB or config
- get_ticketing_config() / update_ticketing_config(): Dynamic admin configuration
- create_ticket_from_low_confidence(): Auto-generate tickets from low-confidence RAG answers
- get_ticket(): Retrieve a single ticket model
- get_ticket_detail_enriched(): Retrieve enriched TicketDetail with QueryLog, SLA, and expert profile
- list_tickets_scoped(): List with multi-attribute filtering and role-based domain scoping
- get_ticket_dashboard() / get_ticket_statistics(): Admin dashboard statistics and metrics
- assign_ticket(), change_ticket_priority(), change_ticket_status(): Administrative operations
- resolve_ticket(), close_ticket(), add_internal_notes(): Resolution and triage actions
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.permissions import Permission, Role, role_has_any_permission
from app.models.audit_log import AuditLog
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.feedback import Feedback
from app.models.query_log import QueryLog
from app.models.system_setting import SystemSetting
from app.models.ticket import (
    RESOLUTION_TYPES,
    ResolutionType,
    Ticket,
    TicketPriority,
    TicketStatus,
)
from app.models.user import User
from app.models.user_domain import UserDomain
from app.schemas.ticket import (
    QueryHistoryOut,
    TicketConfigUpdateRequest,
    TicketDetail,
    UserMiniOut,
)

logger = logging.getLogger(__name__)

# System Setting Key Constants
SETTING_KEY_THRESHOLD = "ticket_confidence_threshold"
SETTING_KEY_ENABLED = "ticketing_enabled"
SETTING_KEY_DEFAULT_PRIORITY = "ticket_default_priority"
SETTING_KEY_DEFAULT_DOMAIN = "ticket_default_domain"


def new_ticket_id() -> str:
    """Generate a unique ticket ID."""
    prefix = getattr(settings, "ticket_id_prefix", "TKT")
    return f"{prefix}_{uuid.uuid4().hex[:10].upper()}"


# ── Domain Scoping Helpers (Multi-Tenant RBAC) ────────────────────────────────

def get_user_authorized_domain_ids(
    db: Session,
    user: Optional[User],
    role: Role,
) -> Optional[Set[uuid.UUID]]:
    """
    Returns the set of domain UUIDs the user is authorized to manage.
    - Super Admin / Platform Owner: None (represents unrestricted global access).
    - Domain Manager: Set of domain IDs assigned in user_domains or domain_routing_configs.
    - Other roles: Empty set (can only view own tickets).
    """
    if role in (Role.PLATFORM_OWNER, Role.SUPER_ADMIN):
        return None  # Unrestricted global access

    if not user or not hasattr(user, "id") or user.id is None:
        return set()

    if role == Role.DOMAIN_MANAGER:
        domain_ids: Set[uuid.UUID] = set()

        # 1. Domains from user_domains table
        ud_rows = db.query(UserDomain.domain_id).filter(UserDomain.user_id == user.id).all()
        for row in ud_rows:
            if row[0]:
                domain_ids.add(row[0])

        # 2. Domains from domain_routing_configs table
        drc_rows = (
            db.query(DomainRoutingConfig.domain_id)
            .filter(
                DomainRoutingConfig.manager_user_id == user.id,
                DomainRoutingConfig.is_active.is_(True),
            )
            .all()
        )
        for row in drc_rows:
            if row[0]:
                domain_ids.add(row[0])

        return domain_ids

    return set()


def get_user_authorized_domain_names(
    db: Session,
    user: Optional[User],
    role: Role,
) -> Optional[Set[str]]:
    """
    Returns the set of lowercased domain keys/names the user is authorized to manage.
    Returns None for platform-wide admins.
    """
    domain_ids = get_user_authorized_domain_ids(db, user, role)
    if domain_ids is None:
        return None

    if not domain_ids:
        return set()

    domains = db.query(Domain).filter(Domain.id.in_(domain_ids)).all()
    names: Set[str] = set()
    for d in domains:
        if d.key:
            names.add(d.key.lower())
        if d.name:
            names.add(d.name.lower())
    return names


def can_user_access_ticket(
    db: Session,
    ticket: Ticket,
    current_user: Optional[User],
    caller_role: Role,
) -> bool:
    """Check if the caller has permission to view/manage this specific ticket."""
    if caller_role in (Role.PLATFORM_OWNER, Role.SUPER_ADMIN):
        return True

    if not current_user or not hasattr(current_user, "id"):
        return False

    # Owner can always see their own ticket
    if ticket.user_id and str(ticket.user_id) == str(current_user.id):
        return True

    # Assigned expert can access
    if ticket.assigned_to and str(ticket.assigned_to) == str(current_user.id):
        return True

    # Domain Manager scoping check
    if caller_role == Role.DOMAIN_MANAGER:
        authorized_ids = get_user_authorized_domain_ids(db, current_user, caller_role)
        if authorized_ids is not None:
            if ticket.routed_domain_id and ticket.routed_domain_id in authorized_ids:
                return True
            authorized_names = get_user_authorized_domain_names(db, current_user, caller_role)
            if authorized_names and ticket.domain and ticket.domain.lower() in authorized_names:
                return True
        return False

    # Reviewer permissions
    if role_has_any_permission(caller_role, (Permission.TICKET_VIEW_DOMAIN,)):
        return True

    return False


# ── Dynamic System Configuration ───────────────────────────────────────────────

def get_ticket_confidence_threshold(db: Optional[Session] = None) -> float:
    """Get the active ticket confidence threshold."""
    if db is not None:
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == SETTING_KEY_THRESHOLD).first()
            if row and row.value:
                return float(row.value)
        except Exception as exc:
            logger.debug("[Ticket Config] Failed to read threshold from DB: %s", exc)
    return float(getattr(settings, "ticket_confidence_threshold", 0.70))


def is_ticketing_enabled(db: Optional[Session] = None) -> bool:
    """Check if automatic ticketing is enabled."""
    if db is not None:
        try:
            row = db.query(SystemSetting).filter(SystemSetting.key == SETTING_KEY_ENABLED).first()
            if row and row.value:
                return row.value.strip().lower() in ("true", "1", "yes", "on")
        except Exception as exc:
            logger.debug("[Ticket Config] Failed to read ticketing_enabled from DB: %s", exc)
    return bool(getattr(settings, "ticketing_enabled", True))


def get_ticketing_config(db: Session) -> dict:
    """Get the full ticketing configuration for administrators."""
    threshold = get_ticket_confidence_threshold(db)
    enabled = is_ticketing_enabled(db)

    setting_row = db.query(SystemSetting).filter(SystemSetting.key == SETTING_KEY_THRESHOLD).first()
    updated_at = setting_row.updated_at if setting_row else None
    updated_by = str(setting_row.updated_by) if setting_row and setting_row.updated_by else None

    return {
        "ticketing_enabled": enabled,
        "ticket_confidence_threshold": threshold,
        "threshold": threshold,
        "ticket_default_priority": getattr(settings, "ticket_default_priority", "medium"),
        "ticket_default_domain": getattr(settings, "ticket_default_domain", "General"),
        "priority_cutoffs": {
            "critical": getattr(settings, "ticket_priority_cutoff_critical", 0.40),
            "high": getattr(settings, "ticket_priority_cutoff_high", 0.60),
            "medium": getattr(settings, "ticket_priority_cutoff_medium", 0.80),
            "low": getattr(settings, "ticket_priority_cutoff_low", 0.90),
        },
        "updated_at": updated_at,
        "updated_by": updated_by,
    }


def update_ticketing_config(
    db: Session,
    update: TicketConfigUpdateRequest,
    admin_user_id: Optional[uuid.UUID] = None,
) -> dict:
    """Update ticketing configuration in the database (Admin only)."""
    if update.ticket_confidence_threshold is not None:
        val = str(update.ticket_confidence_threshold)
        row = db.query(SystemSetting).filter(SystemSetting.key == SETTING_KEY_THRESHOLD).first()
        if row:
            row.value = val
            row.updated_by = admin_user_id
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = SystemSetting(
                key=SETTING_KEY_THRESHOLD,
                value=val,
                description="Minimum verification confidence score required to avoid ticket generation",
                updated_by=admin_user_id,
            )
            db.add(row)
        if hasattr(settings, "ticket_confidence_threshold"):
            settings.ticket_confidence_threshold = update.ticket_confidence_threshold

    if update.ticketing_enabled is not None:
        val = "true" if update.ticketing_enabled else "false"
        row = db.query(SystemSetting).filter(SystemSetting.key == SETTING_KEY_ENABLED).first()
        if row:
            row.value = val
            row.updated_by = admin_user_id
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = SystemSetting(
                key=SETTING_KEY_ENABLED,
                value=val,
                description="Enable or disable automatic ticket generation on low confidence answers",
                updated_by=admin_user_id,
            )
            db.add(row)
        if hasattr(settings, "ticketing_enabled"):
            settings.ticketing_enabled = update.ticketing_enabled

    db.commit()
    return get_ticketing_config(db)


# ── Ticket Generation ──────────────────────────────────────────────────────────

def _calculate_priority_from_confidence(confidence_score: float) -> str:
    """Calculate priority based on confidence gap."""
    if confidence_score < getattr(settings, "ticket_priority_cutoff_critical", 0.40):
        return TicketPriority.CRITICAL.value
    elif confidence_score < getattr(settings, "ticket_priority_cutoff_high", 0.60):
        return TicketPriority.HIGH.value
    elif confidence_score < getattr(settings, "ticket_priority_cutoff_medium", 0.80):
        return TicketPriority.MEDIUM.value
    return TicketPriority.LOW.value


def create_ticket_from_low_confidence(
    db: Session,
    query_id: Optional[str],
    user_id: Optional[str],
    original_question: str,
    generated_answer: str,
    confidence_score: float,
    confidence_threshold: Optional[float] = None,
    evidence: Optional[str] = None,
    domain: Optional[str] = None,
    priority: Optional[str] = None,
    # Phase 11 Routing metadata
    intent: Optional[str] = None,
    entities: Optional[list] = None,
    source_document_ids: Optional[List[str]] = None,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Automatically creates a ticket when confidence < threshold.
    Applies deduplication and 6-tier domain routing.
    """
    threshold = confidence_threshold or get_ticket_confidence_threshold(db)
    user_message = getattr(
        settings,
        "ticket_user_message",
        "Your question requires domain expert verification. A support ticket has been created.",
    )

    if not is_ticketing_enabled(db):
        return None, None

    if confidence_score >= threshold:
        return None, None

    try:
        user_uuid = None
        if user_id:
            try:
                user_uuid = uuid.UUID(str(user_id))
            except ValueError:
                user_uuid = None

        if not priority:
            priority = _calculate_priority_from_confidence(confidence_score)

        # Deduplication check
        existing = (
            db.query(Ticket)
            .filter(
                func.lower(Ticket.original_question) == original_question.strip().lower(),
                Ticket.status.in_([
                    TicketStatus.OPEN.value,
                    TicketStatus.NEEDS_TRIAGE.value,
                    TicketStatus.ROUTED.value,
                ]),
            )
            .first()
        )

        if existing:
            existing.occurrence_count += 1
            if confidence_score < existing.confidence_score:
                existing.confidence_score = confidence_score
                existing.priority = priority
            if generated_answer and len(generated_answer) > len(existing.generated_answer or ""):
                existing.generated_answer = generated_answer
            existing.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(existing)
            logger.info(
                "[Ticket] 🔁 Deduplicated query -> Ticket %s (count=%d)",
                existing.ticket_id, existing.occurrence_count
            )
            return existing, user_message

        ticket_id = new_ticket_id()
        title = f"Low Confidence Answer - {original_question[:60]}..." if len(original_question) > 60 else f"Low Confidence Answer - {original_question}"
        description = (
            f"Automatic ticket generated for low-confidence RAG answer.\n"
            f"Question: {original_question}\n"
            f"Confidence Score: {confidence_score * 100:.2f}%\n"
            f"Threshold: {threshold * 100:.2f}%"
        )

        ticket = Ticket(
            ticket_id=ticket_id,
            query_id=query_id,
            user_id=user_uuid,
            title=title,
            description=description,
            original_question=original_question,
            generated_answer=generated_answer,
            confidence_score=confidence_score,
            confidence_threshold=threshold,
            evidence=evidence,
            priority=priority,
            domain=domain or getattr(settings, "ticket_default_domain", "General"),
            status=TicketStatus.OPEN.value,
            source_document_ids=json.dumps(source_document_ids) if source_document_ids else None,
        )
        db.add(ticket)
        db.flush()

        # Phase 11: Domain routing
        if getattr(settings, "domain_routing_enabled", True):
            try:
                from app.services.domain_router_service import classify_domain, route_ticket as apply_routing
                import asyncio

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    routing_result = _classify_domain_sync(
                        db, original_question, str(user_id) if user_id else None,
                        intent, entities, source_document_ids, domain,
                    )
                else:
                    routing_result = asyncio.run(classify_domain(
                        db,
                        query_text=original_question,
                        user_id=str(user_id) if user_id else None,
                        intent=intent,
                        entities=entities,
                        source_document_ids=source_document_ids,
                        explicit_domain=domain,
                    ))

                apply_routing(db, ticket, routing_result)
                _log_ticket_audit(
                    db,
                    action="ticket_triage_needed" if routing_result.needs_triage else "ticket_routed",
                    ticket=ticket,
                    actor_id=user_uuid,
                    detail=(
                        f"ticket_id={ticket.ticket_id} | "
                        f"domain={routing_result.domain_key or 'none'} | "
                        f"confidence={routing_result.confidence:.2f} | "
                        f"method={routing_result.method} | "
                        f"reasoning={routing_result.reasoning}"
                    ),
                )
            except Exception as route_exc:
                logger.error(
                    "[Ticket] Domain routing failed for ticket %s: %s",
                    ticket_id, route_exc
                )

        db.commit()
        db.refresh(ticket)

        # ── Phase 15: Emit ticket_created learning signal ──────────────────────
        _emit_ticket_created_signal(
            db=db,
            ticket=ticket,
            query_id=query_id,
            confidence_score=confidence_score,
            intent=intent,
        )

        return ticket, user_message

    except Exception as exc:
        db.rollback()
        logger.error("[Ticket] Failed to create ticket for query %s: %s", query_id, exc)
        return None, None


# ── Ticket Retrieval and Enriched Details ─────────────────────────────────────

def get_ticket(db: Session, ticket_id: str) -> Optional[Ticket]:
    """Retrieve a single ticket by ticket_id or UUID."""
    try:
        uid = uuid.UUID(ticket_id)
        t = db.query(Ticket).filter(or_(Ticket.ticket_id == ticket_id, Ticket.id == uid)).first()
        if t:
            return t
    except ValueError:
        pass
    return db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()


def get_ticket_detail_enriched(
    db: Session,
    ticket_id: str,
    current_user: Optional[User],
    caller_role: Role,
) -> Optional[TicketDetail]:
    """
    Retrieve full enriched TicketDetail including:
    - Assigned expert profile
    - Resolver user profile
    - Associated QueryLog execution telemetry
    - Parsed citations and evidence
    - SLA overdue indicators
    """
    ticket = get_ticket(db, ticket_id)
    if not ticket:
        return None

    if not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    # Expert profile
    assigned_expert = None
    if ticket.assigned_to:
        try:
            exp_uid = uuid.UUID(str(ticket.assigned_to))
            u = db.query(User).filter(User.id == exp_uid).first()
            if u:
                assigned_expert = UserMiniOut(
                    id=str(u.id), email=u.email, full_name=u.full_name, role=u.role
                )
        except (ValueError, TypeError):
            pass

    # Resolver profile
    resolver_user = None
    if ticket.resolver_user_id:
        try:
            res_uid = uuid.UUID(str(ticket.resolver_user_id))
            ru = db.query(User).filter(User.id == res_uid).first()
            if ru:
                resolver_user = UserMiniOut(
                    id=str(ru.id), email=ru.email, full_name=ru.full_name, role=ru.role
                )
        except (ValueError, TypeError):
            pass

    # Query telemetry from query_logs
    query_history = None
    if ticket.query_id:
        ql = db.query(QueryLog).filter(QueryLog.query_id == ticket.query_id).first()
        if ql:
            query_history = QueryHistoryOut(
                query_id=ql.query_id,
                query_text=ql.query_text,
                latency_ms=ql.latency_ms,
                search_method=ql.route,
                retrieval_mode=ql.retrieval_strategy,
                model_name=ql.model_used,
                created_at=ql.created_at,
            )

    detail = TicketDetail.model_validate(ticket)
    detail.assigned_domain_expert = assigned_expert
    detail.assigned_expert = assigned_expert
    detail.resolver_user = resolver_user
    detail.query_history = query_history
    return detail


# ── Scoped List & Multi-Filter Querying ───────────────────────────────────────

def list_tickets_scoped(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
    skip: int = 0,
    limit: int = 50,
    filters: Optional[dict] = None,
) -> Tuple[List[Ticket], int, str]:
    """
    List tickets with multi-attribute filtering and strict role-based domain scoping.
    Filters:
      - status: exact status (e.g. open, in_progress, resolved)
      - priority: exact priority (e.g. critical, high, medium, low)
      - domain: domain key or department
      - assigned_to: specific expert UUID or 'unassigned'
      - date_from / date_to: date range filter on created_at
      - min_confidence / max_confidence: confidence score range
      - is_overdue: boolean
      - search_text: text search in title/description/question/resolution
    """
    q = db.query(Ticket)

    # 1. Apply RBAC Domain Scoping
    if caller_role in (Role.PLATFORM_OWNER, Role.SUPER_ADMIN):
        scope = "global"
    elif caller_role == Role.DOMAIN_MANAGER:
        authorized_ids = get_user_authorized_domain_ids(db, current_user, caller_role)
        authorized_names = get_user_authorized_domain_names(db, current_user, caller_role)

        conditions = []
        if authorized_ids:
            conditions.append(Ticket.routed_domain_id.in_(authorized_ids))
        if authorized_names:
            conditions.append(func.lower(Ticket.domain).in_(authorized_names))
        # Domain Manager can also see tickets assigned to them personally
        if current_user and hasattr(current_user, "id"):
            conditions.append(Ticket.assigned_to == str(current_user.id))

        if conditions:
            q = q.filter(or_(*conditions))
            scope = "domain_managed"
        else:
            q = q.filter(Ticket.user_id == current_user.id if current_user else None)
            scope = "own"
    elif role_has_any_permission(caller_role, (Permission.TICKET_VIEW_DOMAIN,)):
        scope = "reviewer"
    elif current_user and hasattr(current_user, "id") and current_user.id is not None:
        q = q.filter(Ticket.user_id == current_user.id)
        scope = "own"
    else:
        return [], 0, "none"

    # 2. Apply Dynamic Filters
    if filters:
        if filters.get("status"):
            st = filters["status"].strip().lower()
            q = q.filter(func.lower(Ticket.status) == st)

        if filters.get("priority"):
            pr = filters["priority"].strip().lower()
            q = q.filter(func.lower(Ticket.priority) == pr)

        if filters.get("resolution_type"):
            res_t = filters["resolution_type"].strip().upper()
            q = q.filter(func.upper(Ticket.resolution_type) == res_t)

        if filters.get("domain"):
            dom = filters["domain"].strip()
            q = q.filter(Ticket.domain.ilike(f"%{dom}%"))

        if filters.get("user_id"):
            if scope != "own":
                q = q.filter(Ticket.user_id == filters["user_id"])

        if filters.get("assigned_to"):
            assignee = str(filters["assigned_to"]).strip().lower()
            if assignee in ("unassigned", "none", "null"):
                q = q.filter(Ticket.assigned_to.is_(None))
            else:
                q = q.filter(Ticket.assigned_to == filters["assigned_to"])

        if filters.get("date_from"):
            q = q.filter(Ticket.created_at >= filters["date_from"])

        if filters.get("date_to"):
            q = q.filter(Ticket.created_at <= filters["date_to"])

        if filters.get("min_confidence") is not None:
            q = q.filter(Ticket.confidence_score >= filters["min_confidence"])

        if filters.get("max_confidence") is not None:
            q = q.filter(Ticket.confidence_score <= filters["max_confidence"])

        if filters.get("search_text"):
            term = f"%{filters['search_text'].strip()}%"
            q = q.filter(
                Ticket.title.ilike(term) |
                Ticket.description.ilike(term) |
                Ticket.original_question.ilike(term) |
                Ticket.generated_answer.ilike(term) |
                Ticket.resolution.ilike(term) |
                Ticket.ticket_id.ilike(term)
            )

    # 3. Handle is_overdue filter
    if filters and filters.get("is_overdue"):
        # Filter tickets that are overdue based on priority SLA cutoffs
        now_utc = datetime.now(timezone.utc)
        overdue_clauses = [
            and_(func.lower(Ticket.priority) == "critical", Ticket.created_at <= now_utc - timedelta(hours=24)),
            and_(func.lower(Ticket.priority) == "high", Ticket.created_at <= now_utc - timedelta(hours=48)),
            and_(func.lower(Ticket.priority) == "medium", Ticket.created_at <= now_utc - timedelta(hours=72)),
            and_(func.lower(Ticket.priority) == "low", Ticket.created_at <= now_utc - timedelta(hours=120)),
        ]
        q = q.filter(
            ~func.lower(Ticket.status).in_(["resolved", "closed", "rejected"]),
            or_(*overdue_clauses),
        )

    total = q.count()
    tickets = q.order_by(Ticket.created_at.desc()).offset(skip).limit(limit).all()
    return tickets, total, scope


# ── Ticket Dashboard & Queue Statistics ───────────────────────────────────────

def get_ticket_dashboard(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
    domain_filter: Optional[str] = None,
) -> dict:
    """
    Computes comprehensive Admin Panel Ticket Dashboard metrics and analytics:
    - total_tickets, open_tickets, unassigned_tickets, in_progress_tickets, resolved_tickets, closed_tickets
    - overdue_tickets (exceeding priority SLA cutoff)
    - avg_resolution_time (seconds & hours)
    - low_confidence_ticket_count
    - by_status, by_domain, by_priority, by_routing_method breakdowns
    """
    q = db.query(Ticket)

    # Apply role scoping
    if caller_role in (Role.PLATFORM_OWNER, Role.SUPER_ADMIN):
        pass
    elif caller_role == Role.DOMAIN_MANAGER:
        authorized_ids = get_user_authorized_domain_ids(db, current_user, caller_role)
        authorized_names = get_user_authorized_domain_names(db, current_user, caller_role)
        conditions = []
        if authorized_ids:
            conditions.append(Ticket.routed_domain_id.in_(authorized_ids))
        if authorized_names:
            conditions.append(func.lower(Ticket.domain).in_(authorized_names))
        if current_user and hasattr(current_user, "id"):
            conditions.append(Ticket.assigned_to == str(current_user.id))
        if conditions:
            q = q.filter(or_(*conditions))
        else:
            q = q.filter(Ticket.user_id == current_user.id if current_user else None)
    elif not role_has_any_permission(caller_role, (Permission.TICKET_VIEW_DOMAIN,)):
        if current_user and hasattr(current_user, "id") and current_user.id is not None:
            q = q.filter(Ticket.user_id == current_user.id)
        else:
            return _empty_dashboard_dict()

    if domain_filter:
        q = q.filter(Ticket.domain.ilike(f"%{domain_filter.strip()}%"))

    total = q.count()

    # Granular status counts
    status_counts: Dict[str, int] = {}
    for st in TicketStatus:
        status_counts[st.value] = q.filter(func.lower(Ticket.status) == st.value.lower()).count()

    open_tickets = (
        status_counts.get(TicketStatus.OPEN.value, 0)
        + status_counts.get(TicketStatus.ROUTED.value, 0)
        + status_counts.get(TicketStatus.NEEDS_TRIAGE.value, 0)
    )

    unassigned_tickets = q.filter(
        Ticket.assigned_to.is_(None),
        ~func.lower(Ticket.status).in_(["resolved", "closed", "rejected"]),
    ).count()

    in_progress_tickets = (
        status_counts.get(TicketStatus.IN_PROGRESS.value, 0)
        + status_counts.get(TicketStatus.ASSIGNED.value, 0)
        + status_counts.get(TicketStatus.IN_REVIEW.value, 0)
    )

    resolved_tickets = status_counts.get(TicketStatus.RESOLVED.value, 0)
    closed_tickets = status_counts.get(TicketStatus.CLOSED.value, 0)

    # Overdue tickets calculation
    now_utc = datetime.now(timezone.utc)
    overdue_clauses = [
        and_(func.lower(Ticket.priority) == "critical", Ticket.created_at <= now_utc - timedelta(hours=24)),
        and_(func.lower(Ticket.priority) == "high", Ticket.created_at <= now_utc - timedelta(hours=48)),
        and_(func.lower(Ticket.priority) == "medium", Ticket.created_at <= now_utc - timedelta(hours=72)),
        and_(func.lower(Ticket.priority) == "low", Ticket.created_at <= now_utc - timedelta(hours=120)),
    ]
    overdue_tickets = q.filter(
        ~func.lower(Ticket.status).in_(["resolved", "closed", "rejected"]),
        or_(*overdue_clauses),
    ).count()

    # Low-confidence ticket count
    low_confidence_ticket_count = q.filter(
        Ticket.confidence_score < Ticket.confidence_threshold
    ).count()

    # Priority distribution
    priority_counts: Dict[str, int] = {}
    for pr in TicketPriority:
        priority_counts[pr.value] = q.filter(func.lower(Ticket.priority) == pr.value.lower()).count()

    # Domain distribution
    domain_counts: Dict[str, int] = {}
    for dom_name, cnt in (
        q.filter(Ticket.domain.isnot(None))
        .with_entities(Ticket.domain, func.count(Ticket.id))
        .group_by(Ticket.domain)
        .all()
    ):
        domain_counts[dom_name or "General"] = cnt

    # Routing method distribution
    routing_method_counts: Dict[str, int] = {}
    for r_method, cnt in (
        q.filter(Ticket.routing_method.isnot(None))
        .with_entities(Ticket.routing_method, func.count(Ticket.id))
        .group_by(Ticket.routing_method)
        .all()
    ):
        if r_method:
            routing_method_counts[r_method] = cnt

    # Resolution type distribution (Phase 13)
    resolution_type_counts: Dict[str, int] = {}
    for r_type, cnt in (
        q.filter(Ticket.resolution_type.isnot(None))
        .with_entities(Ticket.resolution_type, func.count(Ticket.id))
        .group_by(Ticket.resolution_type)
        .all()
    ):
        if r_type:
            resolution_type_counts[r_type] = cnt

    # Average resolution time
    resolved_rows = (
        q.filter(
            Ticket.resolved_at.isnot(None),
            Ticket.created_at.isnot(None),
        )
        .with_entities(Ticket.created_at, Ticket.resolved_at)
        .all()
    )

    avg_resolution_seconds = None
    avg_resolution_hours = None
    if resolved_rows:
        total_seconds = sum(
            (r_at - c_at).total_seconds() for c_at, r_at in resolved_rows if r_at and c_at and r_at >= c_at
        )
        if len(resolved_rows) > 0:
            avg_resolution_seconds = round(total_seconds / len(resolved_rows), 2)
            avg_resolution_hours = round(avg_resolution_seconds / 3600.0, 2)

    # Average confidence scores
    avg_confidence_open = q.filter(
        func.lower(Ticket.status).in_(["open", "routed", "needs_triage"])
    ).with_entities(func.avg(Ticket.confidence_score)).scalar()

    avg_confidence_all = q.with_entities(func.avg(Ticket.confidence_score)).scalar()

    return {
        "total_tickets": total,
        "open_tickets": open_tickets,
        "unassigned_tickets": unassigned_tickets,
        "in_progress_tickets": in_progress_tickets,
        "resolved_tickets": resolved_tickets,
        "closed_tickets": closed_tickets,
        "overdue_tickets": overdue_tickets,
        "low_confidence_ticket_count": low_confidence_ticket_count,
        "avg_resolution_time_seconds": avg_resolution_seconds,
        "avg_resolution_time_hours": avg_resolution_hours,
        "by_status": status_counts,
        "by_domain": domain_counts,
        "by_priority": priority_counts,
        "by_routing_method": routing_method_counts,
        "by_resolution_type": resolution_type_counts,
        "avg_confidence_open": round(float(avg_confidence_open), 4) if avg_confidence_open else None,
        "avg_confidence_all": round(float(avg_confidence_all), 4) if avg_confidence_all else None,
    }


def _empty_dashboard_dict() -> dict:
    return {
        "total_tickets": 0, "open_tickets": 0, "unassigned_tickets": 0, "in_progress_tickets": 0,
        "resolved_tickets": 0, "closed_tickets": 0, "overdue_tickets": 0, "low_confidence_ticket_count": 0,
        "avg_resolution_time_seconds": None, "avg_resolution_time_hours": None,
        "by_status": {}, "by_domain": {}, "by_priority": {}, "by_routing_method": {}, "by_resolution_type": {},
        "avg_confidence_open": None, "avg_confidence_all": None,
    }


def get_ticket_statistics(
    db: Session,
    current_user: Optional[User],
    caller_role: Role,
) -> dict:
    """Legacy stats function compatible with TicketStatsResponse."""
    dash = get_ticket_dashboard(db, current_user, caller_role)
    status_map = dash.get("by_status", {})
    return {
        "total": dash["total_tickets"],
        "open": status_map.get("open", 0),
        "needs_triage": status_map.get("needs_triage", 0),
        "routed": status_map.get("routed", 0),
        "assigned": status_map.get("assigned", 0),
        "in_progress": status_map.get("in_progress", 0),
        "resolved": status_map.get("resolved", 0),
        "closed": status_map.get("closed", 0),
        "rejected": status_map.get("rejected", 0),
        "unassigned_tickets": dash["unassigned_tickets"],
        "overdue_tickets": dash["overdue_tickets"],
        "low_confidence_ticket_count": dash["low_confidence_ticket_count"],
        "by_domain": dash["by_domain"],
        "by_department": dash["by_domain"],
        "by_priority": dash["by_priority"],
        "by_routing_method": dash["by_routing_method"],
        "by_resolution_type": dash.get("by_resolution_type", {}),
        "avg_confidence_open": dash["avg_confidence_open"],
        "avg_confidence_all": dash["avg_confidence_all"],
        "avg_resolution_time_hours": dash["avg_resolution_time_hours"],
        "avg_resolution_time_seconds": dash["avg_resolution_time_seconds"],
    }


# ── Administrative Action Mutations ──────────────────────────────────────────

def assign_ticket(
    db: Session,
    ticket_id: str,
    assigned_to: str,
    current_user: User,
    caller_role: Role,
    notes: Optional[str] = None,
) -> Optional[Ticket]:
    """Assign or reassign a ticket to a domain expert."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    prev_assignee = ticket.assigned_to
    if assigned_to.strip().lower() in ("unassigned", "none", "null", ""):
        ticket.assigned_to = None
        ticket.assigned_at = None
        ticket.status = TicketStatus.OPEN.value if ticket.status == TicketStatus.ASSIGNED.value else ticket.status
    else:
        try:
            target_uid = uuid.UUID(assigned_to)
            target_user = db.query(User).filter(User.id == target_uid, User.is_active.is_(True)).first()
            if not target_user:
                return None
            ticket.assigned_to = str(target_user.id)
            ticket.assigned_at = datetime.now(timezone.utc)
            if ticket.status in (TicketStatus.OPEN.value, TicketStatus.ROUTED.value, TicketStatus.NEEDS_TRIAGE.value):
                ticket.status = TicketStatus.ASSIGNED.value
        except (ValueError, TypeError):
            return None

    if notes:
        ticket.feedback = f"[{current_user.email} - Assign Note]: {notes}" + (f"\n{ticket.feedback}" if ticket.feedback else "")

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_assigned",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=f"ticket_id={ticket.ticket_id} | from={prev_assignee} | to={ticket.assigned_to} | notes={notes or 'none'}",
    )
    return ticket


def change_ticket_priority(
    db: Session,
    ticket_id: str,
    priority: str,
    current_user: User,
    caller_role: Role,
    notes: Optional[str] = None,
) -> Optional[Ticket]:
    """Change priority level of a ticket."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    prev_priority = ticket.priority
    ticket.priority = priority.strip().lower()
    if notes:
        ticket.feedback = f"[{current_user.email} - Priority Change]: {notes}" + (f"\n{ticket.feedback}" if ticket.feedback else "")
    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_priority_changed",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=f"ticket_id={ticket.ticket_id} | from={prev_priority} | to={ticket.priority} | notes={notes or 'none'}",
    )
    return ticket


def change_ticket_status(
    db: Session,
    ticket_id: str,
    status_val: str,
    current_user: User,
    caller_role: Role,
    notes: Optional[str] = None,
) -> Optional[Ticket]:
    """Change lifecycle status of a ticket."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    prev_status = ticket.status
    norm_status = status_val.strip().lower()
    ticket.status = norm_status

    if norm_status in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value, TicketStatus.REJECTED.value):
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.now(timezone.utc)
        if not ticket.resolver_user_id:
            ticket.resolver_user_id = current_user.id
    elif norm_status == TicketStatus.ASSIGNED.value and not ticket.assigned_at:
        ticket.assigned_at = datetime.now(timezone.utc)

    if notes:
        ticket.feedback = f"[{current_user.email} - Status Change]: {notes}" + (f"\n{ticket.feedback}" if ticket.feedback else "")

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_status_changed",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=f"ticket_id={ticket.ticket_id} | from={prev_status} | to={ticket.status} | notes={notes or 'none'}",
    )
    return ticket


def resolve_ticket(
    db: Session,
    ticket_id: str,
    resolution: str,
    current_user: User,
    caller_role: Role,
    resolution_type: Optional[str] = None,
    internal_notes: Optional[str] = None,
    supporting_evidence: Optional[str] = None,
    supporting_document_ids: Optional[List[str]] = None,
) -> Optional[Ticket]:
    """
    Resolve a ticket with domain expert verified answer (Phase 13).
    Requires resolution, resolution_type, resolved_by, and resolved_at.
    Stores feedback for Continuous Learning module (without mutating KB index).
    """
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    # Validate resolution type
    norm_res_type = (resolution_type or ResolutionType.OTHER.value).strip().upper()
    if norm_res_type not in RESOLUTION_TYPES:
        norm_res_type = ResolutionType.OTHER.value

    ticket.resolution = resolution.strip()
    ticket.resolution_type = norm_res_type
    ticket.status = TicketStatus.RESOLVED.value
    ticket.resolved_at = datetime.now(timezone.utc)
    ticket.resolver_user_id = current_user.id

    if supporting_evidence is not None:
        ticket.supporting_evidence = supporting_evidence.strip() if supporting_evidence else None

    if supporting_document_ids is not None:
        ticket.supporting_document_ids = json.dumps(supporting_document_ids) if supporting_document_ids else None

    if internal_notes:
        note_entry = f"[{current_user.email} - Resolution Notes ({norm_res_type})]: {internal_notes.strip()}"
        ticket.feedback = f"{note_entry}\n\n{ticket.feedback}" if ticket.feedback else note_entry

    # ── Continuous Learning Feedback Integration ─────────────────────────────
    # Feed the verified correction into the Continuous Learning module
    # without mutating knowledge base vectors directly.
    if ticket.query_id:
        try:
            existing_fb = db.query(Feedback).filter(Feedback.query_id == ticket.query_id).first()
            if existing_fb:
                existing_fb.correction_text = resolution.strip()
                existing_fb.rating = "down"
            else:
                fb_row = Feedback(
                    feedback_id=f"FB_{uuid.uuid4().hex[:10].upper()}",
                    query_id=ticket.query_id,
                    rating="down",
                    correction_text=resolution.strip(),
                )
                db.add(fb_row)

            # Update associated QueryLog telemetry
            ql = db.query(QueryLog).filter(QueryLog.query_id == ticket.query_id).first()
            if ql:
                ql.ticket_status = TicketStatus.RESOLVED.value
        except Exception as fb_exc:
            logger.warning("[Ticket] Continuous learning feedback integration: %s", fb_exc)

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_resolved",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=(
            f"ticket_id={ticket.ticket_id} | "
            f"resolution_type={ticket.resolution_type} | "
            f"resolved_by={current_user.email} | "
            f"supporting_docs={ticket.supporting_document_ids or 'none'}"
        ),
    )

    # ── Phase 15: Emit ticket_resolved (and secondary) learning signals ────────
    _emit_ticket_resolved_signals(
        db=db,
        ticket=ticket,
        resolution_type=norm_res_type,
    )

    return ticket


def close_ticket(
    db: Session,
    ticket_id: str,
    current_user: User,
    caller_role: Role,
    feedback: Optional[str] = None,
) -> Optional[Ticket]:
    """Close a ticket."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    ticket.status = TicketStatus.CLOSED.value
    if not ticket.resolved_at:
        ticket.resolved_at = datetime.now(timezone.utc)
    if not ticket.resolver_user_id:
        ticket.resolver_user_id = current_user.id

    if feedback:
        ticket.feedback = f"[{current_user.email} - Close]: {feedback}" + (f"\n{ticket.feedback}" if ticket.feedback else "")

    ticket.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_closed",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=f"ticket_id={ticket.ticket_id} | closed_by={current_user.email}",
    )
    return ticket


def add_internal_notes(
    db: Session,
    ticket_id: str,
    notes: str,
    current_user: User,
    caller_role: Role,
) -> Optional[Ticket]:
    """Append internal triage notes to a ticket."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    new_note = f"[{timestamp_str} | {current_user.email}]: {notes.strip()}"
    ticket.feedback = f"{new_note}\n\n{ticket.feedback}" if ticket.feedback else new_note
    ticket.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(ticket)

    _log_ticket_audit(
        db,
        action="ticket_notes_added",
        ticket=ticket,
        actor_id=current_user.id,
        actor_email=current_user.email,
        detail=f"ticket_id={ticket.ticket_id} | note_length={len(notes)}",
    )
    return ticket


def update_ticket(
    db: Session,
    ticket_id: str,
    current_user: Optional[User],
    caller_role: Role,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    resolution: Optional[str] = None,
    resolution_type: Optional[str] = None,
    supporting_evidence: Optional[str] = None,
    supporting_document_ids: Optional[List[str]] = None,
    feedback: Optional[str] = None,
) -> Optional[Ticket]:
    """General update method for tickets."""
    ticket = get_ticket(db, ticket_id)
    if not ticket or not can_user_access_ticket(db, ticket, current_user, caller_role):
        return None

    if status:
        norm = status.strip().lower()
        ticket.status = norm
        if norm in (TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value, TicketStatus.REJECTED.value):
            if not ticket.resolved_at:
                ticket.resolved_at = datetime.now(timezone.utc)
            if current_user and hasattr(current_user, "id") and not ticket.resolver_user_id:
                ticket.resolver_user_id = current_user.id
        elif norm == TicketStatus.ASSIGNED.value and not ticket.assigned_at:
            ticket.assigned_at = datetime.now(timezone.utc)

    if priority:
        ticket.priority = priority.strip().lower()

    if assigned_to is not None:
        if assigned_to.strip().lower() in ("unassigned", "none", "null", ""):
            ticket.assigned_to = None
            ticket.assigned_at = None
        else:
            try:
                ticket.assigned_to = str(uuid.UUID(assigned_to))
                ticket.assigned_at = datetime.now(timezone.utc)
                if ticket.status == TicketStatus.OPEN.value:
                    ticket.status = TicketStatus.ASSIGNED.value
            except (ValueError, TypeError):
                pass

    if resolution is not None:
        ticket.resolution = resolution or None
        if not ticket.resolved_at:
            ticket.resolved_at = datetime.now(timezone.utc)
        if current_user and hasattr(current_user, "id") and not ticket.resolver_user_id:
            ticket.resolver_user_id = current_user.id

    if resolution_type is not None:
        norm_res_t = resolution_type.strip().upper()
        ticket.resolution_type = norm_res_t if norm_res_t in RESOLUTION_TYPES else ResolutionType.OTHER.value

    if supporting_evidence is not None:
        ticket.supporting_evidence = supporting_evidence.strip() if supporting_evidence else None

    if supporting_document_ids is not None:
        ticket.supporting_document_ids = json.dumps(supporting_document_ids) if supporting_document_ids else None

    if feedback is not None:
        ticket.feedback = feedback or None

    ticket.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
        db.refresh(ticket)
        return ticket
    except Exception as exc:
        db.rollback()
        logger.error("[Ticket] Update failed: %s", exc)
        return None


# ── Internal Helpers & Audit Logging ──────────────────────────────────────────

def _classify_domain_sync(
    db: Session,
    query_text: str,
    user_id: Optional[str],
    intent: Optional[str],
    entities: Optional[list],
    source_document_ids: Optional[List[str]],
    explicit_domain: Optional[str],
):
    """Synchronous domain classification fallback."""
    from app.services.domain_router_service import (
        _try_explicit_domain,
        _try_user_domain,
        _try_intent_keywords,
        _try_ner_entities,
        _try_document_domains,
        _create_triage_result,
    )

    threshold = getattr(settings, "domain_routing_confidence_threshold", 0.50)

    for strategy_fn, args in [
        (_try_explicit_domain, (db, explicit_domain)),
        (_try_user_domain, (db, user_id)),
        (_try_intent_keywords, (db, query_text, intent)),
        (_try_ner_entities, (db, entities)),
        (_try_document_domains, (db, source_document_ids)),
    ]:
        result = strategy_fn(*args)
        if result and result.confidence >= threshold:
            return result

    return _create_triage_result(query_text)


def _log_ticket_audit(
    db: Session,
    action: str,
    ticket: Ticket,
    actor_id: Optional[uuid.UUID] = None,
    actor_email: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Record an audit log for ticket operations (best-effort, never raises)."""
    try:
        row = AuditLog(
            event_type=action,
            actor_id=actor_id,
            actor_email=actor_email,
            detail=detail or f"ticket_id={ticket.ticket_id} | status={ticket.status} | domain={ticket.domain}",
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        logger.error("[Audit] Failed to log ticket event %s: %s", action, exc)


# ── Backward Compatibility ───────────────────────────────────────────────────

def maybe_create_ticket(
    db: Session,
    query_id: Optional[str] = None,
    query_text: Optional[str] = None,
    answer_text: Optional[str] = None,
    confidence_score: Optional[float] = None,
    department: Optional[str] = None,
    source_document_ids: Optional[List[str]] = None,
    hallucinations_detected: int = 0,
    raised_by_user_id: Optional[uuid.UUID] = None,
    intent: Optional[str] = None,
    entities: Optional[list] = None,
    **kwargs,
) -> Optional[Ticket]:
    """Backward compatibility helper for ticket creation."""
    if confidence_score is None or not query_text:
        return None

    res = create_ticket_from_low_confidence(
        db,
        query_id=query_id,
        user_id=str(raised_by_user_id) if raised_by_user_id else None,
        original_question=query_text,
        generated_answer=answer_text or "",
        confidence_score=confidence_score,
        domain=department,
        source_document_ids=source_document_ids,
        intent=intent,
        entities=entities,
    )
    if not res:
        return None
    ticket, _ = res
    if ticket and (source_document_ids or hallucinations_detected):
        if source_document_ids:
            ticket.source_document_ids = json.dumps(source_document_ids)
        if hallucinations_detected:
            ticket.hallucinations_detected = hallucinations_detected
        db.commit()
        db.refresh(ticket)
    return ticket


# ── Phase 15: Learning Signal Helpers ─────────────────────────────────────────

def _emit_ticket_created_signal(
    db: Session,
    ticket: Ticket,
    query_id: Optional[str],
    confidence_score: float,
    intent: Optional[str],
) -> None:
    """
    Emit a ticket_created learning signal after a ticket is successfully committed.
    Non-critical: failures are logged and swallowed.
    """
    try:
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal
        record_signal(
            db,
            LearningSignalType.TICKET_CREATED,
            query_id=query_id,
            ticket_id=ticket.ticket_id,
            confidence_score=confidence_score,
            retrieval_route=None,
            intent=intent,
            details={
                "priority": ticket.priority,
                "domain": ticket.domain,
                "routing_method": ticket.routing_method,
                "needs_triage": ticket.needs_triage,
            },
        )
    except Exception as exc:
        logger.warning("[Ticket] ticket_created signal emission failed (non-critical): %s", exc)


def _emit_ticket_resolved_signals(
    db: Session,
    ticket: Ticket,
    resolution_type: str,
) -> None:
    """
    Emit ticket_resolved and any secondary signals based on resolution type.

    Secondary signals emitted:
      - RETRIEVAL_FAILURE  if resolution_type == RETRIEVAL_FAILURE
      - HALLUCINATION_DETECTED  if resolution_type == INCORRECT_GENERATION

    Non-critical: failures are logged and swallowed.
    """
    try:
        from app.models.learning_signal import LearningSignalType
        from app.services.learning_signals_service import record_signal
        from app.models.ticket import ResolutionType

        common = dict(
            query_id=ticket.query_id,
            ticket_id=ticket.ticket_id,
            confidence_score=ticket.confidence_score,
            resolution_type=resolution_type,
            details={
                "resolution_type": resolution_type,
                "domain": ticket.domain,
                "priority": ticket.priority,
                "routing_method": ticket.routing_method,
            },
        )

        # Primary: ticket resolved
        record_signal(db, LearningSignalType.TICKET_RESOLVED, was_correct="no", **common)

        # Secondary: retrieval failure
        if resolution_type == ResolutionType.RETRIEVAL_FAILURE.value:
            record_signal(
                db,
                LearningSignalType.RETRIEVAL_FAILURE,
                was_correct="no",
                details={"source": "expert_resolution", "resolution_type": resolution_type},
                query_id=ticket.query_id,
                ticket_id=ticket.ticket_id,
                confidence_score=ticket.confidence_score,
            )

        # Secondary: hallucination detected (expert confirmed LLM fabricated)
        if resolution_type == ResolutionType.INCORRECT_GENERATION.value:
            record_signal(
                db,
                LearningSignalType.HALLUCINATION_DETECTED,
                was_correct="no",
                details={"source": "expert_resolution", "resolution_type": resolution_type},
                query_id=ticket.query_id,
                ticket_id=ticket.ticket_id,
                confidence_score=ticket.confidence_score,
            )

    except Exception as exc:
        logger.warning("[Ticket] ticket_resolved signal emission failed (non-critical): %s", exc)
