"""
Domain Router Service  –  Phase 11: Domain-Based Ticket Routing
--------------------------------------------------------------------
Multi-strategy domain classifier that determines which organizational
domain (HR, Finance, IT, …) a support ticket belongs to.

Cascading resolution order (first match with sufficient confidence wins):
  1. Explicit user-selected domain (if caller passes one)
  2. User's assigned primary domain (from user_domains table)
  3. Query Intelligence / intent + keyword heuristic
  4. Named Entity Recognition (NER) keyword mapping
  5. Retrieved document domains (from source doc domain_id)
  6. LLM-based domain classification (few-shot prompt, fallback)

If no strategy produces a match with confidence ≥
DOMAIN_ROUTING_CONFIDENCE_THRESHOLD, the ticket is flagged NEEDS_TRIAGE
and routed to an administrator — never silently guessed.

Entry points:
  classify_domain(...)  → DomainRoutingResult
  route_ticket(...)     → applies routing to a Ticket row
  get_domain_managers(...)  → domain experts for auto-assignment
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.domain import Domain
from app.models.domain_routing_config import DomainRoutingConfig
from app.models.ticket import Ticket, TicketStatus
from app.models.user import User
from app.models.user_domain import UserDomain

logger = logging.getLogger(__name__)


# ── Domain keyword mapping ─────────────────────────────────────────────────────
# Configurable lookup: domain key → keywords that signal that domain.
# Case-insensitive matching. A future phase could move this to the DB.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "hr": [
        "leave", "maternity", "paternity", "salary", "payroll", "employee",
        "onboarding", "resignation", "benefits", "attendance", "hiring",
        "recruitment", "probation", "termination", "appraisal", "performance review",
        "workplace", "harassment", "grievance", "training", "hr policy",
        "human resources", "sick leave", "annual leave", "vacation",
        "compensation", "bonus", "overtime", "shift", "roster",
    ],
    "finance": [
        "invoice", "budget", "expense", "reimbursement", "payment",
        "accounting", "tax", "audit", "billing", "revenue", "profit",
        "loss", "financial", "purchase order", "procurement", "vendor",
        "accounts payable", "accounts receivable", "cash flow", "forecast",
        "cost center", "ledger", "journal entry", "fiscal",
    ],
    "it": [
        "vpn", "password", "reset", "laptop", "software", "access",
        "email", "network", "server", "security", "firewall", "wifi",
        "computer", "hardware", "printer", "antivirus", "malware",
        "backup", "cloud", "database", "system", "login", "two-factor",
        "mfa", "active directory", "helpdesk", "tech support",
        "installation", "update", "patch", "monitor", "keyboard",
    ],
    "legal": [
        "contract", "compliance", "nda", "regulation", "intellectual property",
        "lawsuit", "litigation", "legal", "trademark", "patent",
        "copyright", "arbitration", "dispute", "liability", "indemnity",
        "governance", "terms of service", "privacy policy",
    ],
    "operations": [
        "logistics", "supply chain", "warehouse", "inventory",
        "shipping", "delivery", "manufacturing", "production",
        "quality control", "facilities", "maintenance", "fleet",
        "operations", "process improvement", "lean", "six sigma",
    ],
    "sales": [
        "sales", "customer", "client", "lead", "pipeline", "deal",
        "quota", "commission", "crm", "account management",
        "proposal", "pricing", "discount", "territory", "forecast",
    ],
    "engineering": [
        "code", "deploy", "deployment", "ci/cd", "git", "repository",
        "api", "microservice", "architecture", "sprint", "agile",
        "release", "feature", "bug", "testing", "qa", "devops",
        "docker", "kubernetes", "infrastructure",
    ],
}


@dataclass
class DomainRoutingResult:
    """Output of the domain classification pipeline."""
    domain_key: Optional[str]       # e.g. "hr", "finance", "it"
    domain_id: Optional[UUID]       # FK to domains.id
    confidence: float               # 0.0–1.0
    method: str                     # which strategy resolved it
    needs_triage: bool              # True if uncertain
    reasoning: str                  # Human-readable explanation


# ── Strategy 1: Explicit user-selected domain ──────────────────────────────────

def _try_explicit_domain(
    db: Session, explicit_domain: Optional[str]
) -> Optional[DomainRoutingResult]:
    """If the caller explicitly passed a domain key, use it."""
    if not explicit_domain:
        return None

    domain = (
        db.query(Domain)
        .filter(Domain.key == explicit_domain.lower().strip(), Domain.is_active.is_(True))
        .first()
    )
    if domain:
        return DomainRoutingResult(
            domain_key=domain.key,
            domain_id=domain.id,
            confidence=1.0,
            method="user_selected",
            needs_triage=False,
            reasoning=f"User explicitly selected domain '{domain.name}'.",
        )
    return None


# ── Strategy 2: User's assigned domain ─────────────────────────────────────────

def _try_user_domain(
    db: Session, user_id: Optional[str]
) -> Optional[DomainRoutingResult]:
    """Use the user's primary assigned domain."""
    if not user_id:
        return None

    try:
        from uuid import UUID as _UUID
        uid = _UUID(user_id) if isinstance(user_id, str) else user_id
    except (ValueError, AttributeError):
        return None

    row = (
        db.query(Domain)
        .join(UserDomain, UserDomain.domain_id == Domain.id)
        .filter(
            UserDomain.user_id == uid,
            UserDomain.is_primary.is_(True),
            Domain.is_active.is_(True),
        )
        .first()
    )
    if row:
        return DomainRoutingResult(
            domain_key=row.key,
            domain_id=row.id,
            confidence=0.85,
            method="user_domain",
            needs_triage=False,
            reasoning=f"User's primary assigned domain is '{row.name}'.",
        )
    return None


# ── Strategy 3: Intent + keyword heuristic ─────────────────────────────────────

def _try_intent_keywords(
    db: Session, query_text: str, intent: Optional[str]
) -> Optional[DomainRoutingResult]:
    """Map query text + intent to a domain using keyword matching."""
    if not query_text:
        return None

    q_lower = query_text.lower()
    scores: dict[str, float] = {}

    for domain_key, keywords in _DOMAIN_KEYWORDS.items():
        score = 0.0
        matched_kws: list[str] = []
        for kw in keywords:
            if kw in q_lower:
                score += 1.0
                matched_kws.append(kw)
        if score > 0:
            # Normalize score — cap at 0.9 so explicit/user-domain always wins
            scores[domain_key] = min(0.9, 0.5 + (score * 0.15))

    if not scores:
        return None

    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]

    # Look up the domain row
    domain = (
        db.query(Domain)
        .filter(Domain.key == best_key, Domain.is_active.is_(True))
        .first()
    )
    if not domain:
        return None

    return DomainRoutingResult(
        domain_key=domain.key,
        domain_id=domain.id,
        confidence=round(best_score, 3),
        method="intent_keywords",
        needs_triage=False,
        reasoning=f"Query keywords matched domain '{domain.name}' (intent={intent}).",
    )


# ── Strategy 4: NER entity mapping ────────────────────────────────────────────

def _try_ner_entities(
    db: Session, entities: Optional[list]
) -> Optional[DomainRoutingResult]:
    """Map named entities to domains using keyword overlap."""
    if not entities:
        return None

    entity_texts = " ".join(
        e.text.lower() if hasattr(e, "text") else str(e).lower()
        for e in entities
    )
    if not entity_texts.strip():
        return None

    scores: dict[str, float] = {}
    for domain_key, keywords in _DOMAIN_KEYWORDS.items():
        for kw in keywords:
            if kw in entity_texts:
                scores[domain_key] = scores.get(domain_key, 0) + 1.0

    if not scores:
        return None

    best_key = max(scores, key=scores.get)
    best_score = min(0.75, 0.4 + (scores[best_key] * 0.15))

    domain = (
        db.query(Domain)
        .filter(Domain.key == best_key, Domain.is_active.is_(True))
        .first()
    )
    if not domain:
        return None

    return DomainRoutingResult(
        domain_key=domain.key,
        domain_id=domain.id,
        confidence=round(best_score, 3),
        method="ner_entities",
        needs_triage=False,
        reasoning=f"Named entities matched domain '{domain.name}'.",
    )


# ── Strategy 5: Retrieved document domains ────────────────────────────────────

def _try_document_domains(
    db: Session, source_document_ids: Optional[list[str]]
) -> Optional[DomainRoutingResult]:
    """Look up the domain_id of the source documents used in the RAG answer."""
    if not source_document_ids:
        return None

    from app.models.document import Document

    domain_counts: dict[str, int] = {}
    domain_rows: dict[str, Domain] = {}

    for doc_id in source_document_ids:
        doc = db.query(Document).filter(Document.document_id == doc_id).first()
        if doc and doc.domain_id:
            dom = db.query(Domain).filter(Domain.id == doc.domain_id, Domain.is_active.is_(True)).first()
            if dom:
                domain_counts[dom.key] = domain_counts.get(dom.key, 0) + 1
                domain_rows[dom.key] = dom

    if not domain_counts:
        return None

    best_key = max(domain_counts, key=domain_counts.get)
    total_docs = len(source_document_ids)
    agreement = domain_counts[best_key] / total_docs if total_docs > 0 else 0
    confidence = min(0.85, 0.5 + (agreement * 0.35))

    domain = domain_rows[best_key]
    return DomainRoutingResult(
        domain_key=domain.key,
        domain_id=domain.id,
        confidence=round(confidence, 3),
        method="document_domain",
        needs_triage=False,
        reasoning=(
            f"Source documents predominantly from domain '{domain.name}' "
            f"({domain_counts[best_key]}/{total_docs} docs)."
        ),
    )


# ── Strategy 6: LLM-based domain classification (fallback) ────────────────────

_LLM_DOMAIN_PROMPT = """\
You are a domain classifier for an enterprise knowledge system.
Given a user query, classify it into EXACTLY ONE of these organizational domains:
{domains}

Rules:
- Reply with ONLY the domain key (lowercase), nothing else.
- If you are uncertain, reply with "unknown".

Query: {query}
Domain:"""


async def _try_llm_classification(
    db: Session, query_text: str
) -> Optional[DomainRoutingResult]:
    """Few-shot LLM-based domain classification as a last resort."""
    if not settings.domain_routing_llm_enabled:
        return None

    # Build domain list from DB
    active_domains = (
        db.query(Domain)
        .filter(Domain.is_active.is_(True))
        .order_by(Domain.key)
        .all()
    )
    if not active_domains:
        return None

    domain_list = ", ".join(f"{d.key} ({d.name})" for d in active_domains)
    prompt = _LLM_DOMAIN_PROMPT.format(domains=domain_list, query=query_text)

    try:
        from app.services.llm_service import get_llm
        llm = get_llm()
        response = await llm.ainvoke(prompt)
        raw = (response.content if hasattr(response, "content") else str(response)).strip().lower()

        # Try to match the response to a known domain key
        for domain in active_domains:
            if domain.key.lower() in raw:
                return DomainRoutingResult(
                    domain_key=domain.key,
                    domain_id=domain.id,
                    confidence=0.65,
                    method="llm_fallback",
                    needs_triage=False,
                    reasoning=f"LLM classified query into domain '{domain.name}'.",
                )

        if "unknown" in raw:
            logger.info("[DomainRouter] LLM returned 'unknown' for query: %s", query_text[:60])
            return None

        logger.warning("[DomainRouter] LLM returned unparseable domain: %r", raw)
        return None

    except Exception as exc:
        logger.warning("[DomainRouter] LLM domain classification failed: %s", exc)
        return None


# ── NEEDS_TRIAGE fallback ──────────────────────────────────────────────────────

def _create_triage_result(query_text: str) -> DomainRoutingResult:
    """Create a NEEDS_TRIAGE result when no strategy succeeded."""
    return DomainRoutingResult(
        domain_key=None,
        domain_id=None,
        confidence=0.0,
        method="needs_triage",
        needs_triage=True,
        reasoning=(
            f"No domain classification strategy could determine the domain "
            f"with sufficient confidence. Query requires manual triage."
        ),
    )


# ── Public entry points ────────────────────────────────────────────────────────

async def classify_domain(
    db: Session,
    query_text: str,
    user_id: Optional[str] = None,
    intent: Optional[str] = None,
    entities: Optional[list] = None,
    source_document_ids: Optional[list[str]] = None,
    explicit_domain: Optional[str] = None,
) -> DomainRoutingResult:
    """
    Run the multi-strategy domain classification pipeline.

    Tries each strategy in priority order; the first to return a result
    with confidence ≥ the threshold wins. If none succeeds, returns
    NEEDS_TRIAGE.
    """
    if not settings.domain_routing_enabled:
        return DomainRoutingResult(
            domain_key=None, domain_id=None, confidence=0.0,
            method="disabled", needs_triage=False,
            reasoning="Domain routing is disabled.",
        )

    threshold = settings.domain_routing_confidence_threshold

    # Strategy 1: Explicit user-selected domain
    result = _try_explicit_domain(db, explicit_domain)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 1 (explicit): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # Strategy 2: User's assigned domain
    result = _try_user_domain(db, user_id)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 2 (user_domain): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # Strategy 3: Intent + keyword heuristic
    result = _try_intent_keywords(db, query_text, intent)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 3 (intent_keywords): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # Strategy 4: NER entity mapping
    result = _try_ner_entities(db, entities)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 4 (ner_entities): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # Strategy 5: Retrieved document domains
    result = _try_document_domains(db, source_document_ids)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 5 (document_domain): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # Strategy 6: LLM-based domain classification
    result = await _try_llm_classification(db, query_text)
    if result and result.confidence >= threshold:
        logger.info("[DomainRouter] Strategy 6 (llm_fallback): %s (%.2f)", result.domain_key, result.confidence)
        return result

    # All strategies failed → NEEDS_TRIAGE
    logger.warning("[DomainRouter] ⚠️ All strategies failed for query: '%s...' → NEEDS_TRIAGE", query_text[:60])
    return _create_triage_result(query_text)


def get_domain_managers(
    db: Session, domain_id: UUID
) -> List[User]:
    """Fetch active domain managers for a domain, primary first."""
    rows = (
        db.query(User)
        .join(DomainRoutingConfig, DomainRoutingConfig.manager_user_id == User.id)
        .filter(
            DomainRoutingConfig.domain_id == domain_id,
            DomainRoutingConfig.is_active.is_(True),
            User.is_active.is_(True),
        )
        .order_by(DomainRoutingConfig.is_primary_manager.desc())
        .all()
    )
    return rows


def get_triage_admin(db: Session) -> Optional[User]:
    """Find an admin to receive NEEDS_TRIAGE tickets."""
    admin_role = settings.domain_routing_triage_admin_role
    admin = (
        db.query(User)
        .filter(User.role == admin_role, User.is_active.is_(True))
        .first()
    )
    if not admin:
        # Fallback: any platform_owner or super_admin
        admin = (
            db.query(User)
            .filter(
                User.role.in_(["platform_owner", "super_admin"]),
                User.is_active.is_(True),
            )
            .first()
        )
    return admin


def route_ticket(
    db: Session, ticket: Ticket, routing_result: DomainRoutingResult
) -> Ticket:
    """
    Apply a DomainRoutingResult to a Ticket: set routing metadata,
    update status, and auto-assign to the primary domain manager.
    """
    now = datetime.now(timezone.utc)

    # Set routing metadata
    ticket.routed_domain_id = routing_result.domain_id
    ticket.routing_confidence = routing_result.confidence
    ticket.routing_method = routing_result.method
    ticket.routing_timestamp = now
    ticket.needs_triage = routing_result.needs_triage

    # Also set the legacy free-text domain field for backward compat
    if routing_result.domain_key:
        ticket.domain = routing_result.domain_key

    if routing_result.needs_triage:
        # NEEDS_TRIAGE: route to admin, don't auto-assign to domain manager
        ticket.status = TicketStatus.NEEDS_TRIAGE.value
        admin = get_triage_admin(db)
        if admin:
            ticket.assigned_to = admin.id
            ticket.assigned_at = now
            logger.info(
                "[DomainRouter] 🔀 Ticket %s → NEEDS_TRIAGE, assigned to admin %s",
                ticket.ticket_id, admin.email,
            )
        else:
            logger.warning(
                "[DomainRouter] ⚠️ Ticket %s → NEEDS_TRIAGE but no admin found!",
                ticket.ticket_id,
            )
    else:
        # Routed: assign to primary domain manager
        ticket.status = TicketStatus.ROUTED.value
        if routing_result.domain_id:
            managers = get_domain_managers(db, routing_result.domain_id)
            if managers:
                ticket.assigned_to = managers[0].id
                ticket.assigned_at = now
                logger.info(
                    "[DomainRouter] 🔀 Ticket %s → domain '%s', assigned to %s",
                    ticket.ticket_id, routing_result.domain_key, managers[0].email,
                )
            else:
                logger.info(
                    "[DomainRouter] 🔀 Ticket %s → domain '%s' (no managers configured)",
                    ticket.ticket_id, routing_result.domain_key,
                )

    ticket.updated_at = now

    logger.info(
        "[DomainRouter] 📋 Routing summary | ticket=%s domain=%s confidence=%.2f "
        "method=%s triage=%s",
        ticket.ticket_id, routing_result.domain_key, routing_result.confidence,
        routing_result.method, routing_result.needs_triage,
    )

    return ticket


# ── Audit Logging ─────────────────────────────────────────────────────────────

def _log_routing_audit(
    db: Session, ticket: Ticket, routing_result: DomainRoutingResult
) -> None:
    """Record a routing audit event (best-effort, never raises)."""
    try:
        from app.models.audit_log import AuditLog

        event_type = "ticket_triage_needed" if routing_result.needs_triage else "ticket_routed"
        detail = (
            f"ticket_id={ticket.ticket_id} | "
            f"domain={routing_result.domain_key or 'none'} | "
            f"confidence={routing_result.confidence:.2f} | "
            f"method={routing_result.method} | "
            f"reasoning={routing_result.reasoning}"
        )

        row = AuditLog(
            event_type=event_type,
            actor_id=ticket.user_id,
            actor_email=None,
            detail=detail,
        )
        db.add(row)
        db.flush()

        logger.info(
            "[Audit] 📋 %s | ticket=%s domain=%s method=%s",
            event_type, ticket.ticket_id,
            routing_result.domain_key or "none", routing_result.method,
        )
    except Exception as exc:
        logger.error("[Audit] Failed to record routing event: %s", exc)


# ── Domain Manager Management ─────────────────────────────────────────────────

def list_domain_managers_detailed(db: Session, domain_id: UUID) -> list[dict]:
    """Return structured manager info for a domain."""
    rows = (
        db.query(DomainRoutingConfig, User, Domain)
        .join(User, User.id == DomainRoutingConfig.manager_user_id)
        .join(Domain, Domain.id == DomainRoutingConfig.domain_id)
        .filter(DomainRoutingConfig.domain_id == domain_id)
        .order_by(DomainRoutingConfig.is_primary_manager.desc(), User.full_name)
        .all()
    )
    result = []
    for cfg, user, dom in rows:
        result.append({
            "id": str(cfg.id),
            "domain_id": str(dom.id),
            "domain_key": dom.key,
            "domain_name": dom.name,
            "manager_user_id": str(user.id),
            "manager_email": user.email,
            "manager_name": user.full_name,
            "manager_role": user.role,
            "is_primary_manager": cfg.is_primary_manager,
            "is_active": cfg.is_active,
            "created_at": cfg.created_at,
            "updated_at": cfg.updated_at,
        })
    return result


def assign_domain_manager(
    db: Session,
    domain_id: UUID,
    manager_user_id: UUID,
    is_primary: bool = False,
) -> DomainRoutingConfig:
    """Assign or update a user as domain manager for a domain."""
    if is_primary:
        # Demote existing primary managers for this domain
        db.query(DomainRoutingConfig).filter(
            DomainRoutingConfig.domain_id == domain_id,
            DomainRoutingConfig.is_primary_manager.is_(True),
        ).update({"is_primary_manager": False})

    row = (
        db.query(DomainRoutingConfig)
        .filter(
            DomainRoutingConfig.domain_id == domain_id,
            DomainRoutingConfig.manager_user_id == manager_user_id,
        )
        .first()
    )
    if row:
        row.is_primary_manager = is_primary
        row.is_active = True
        row.updated_at = datetime.now(timezone.utc)
    else:
        row = DomainRoutingConfig(
            domain_id=domain_id,
            manager_user_id=manager_user_id,
            is_primary_manager=is_primary,
            is_active=True,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    logger.info(
        "[DomainRouter] 👤 Assigned manager %s to domain %s (primary=%s)",
        manager_user_id, domain_id, is_primary,
    )
    return row


def remove_domain_manager(
    db: Session,
    domain_id: UUID,
    manager_user_id: UUID,
) -> bool:
    """Remove a manager assignment from a domain."""
    deleted = (
        db.query(DomainRoutingConfig)
        .filter(
            DomainRoutingConfig.domain_id == domain_id,
            DomainRoutingConfig.manager_user_id == manager_user_id,
        )
        .delete()
    )
    db.commit()
    return deleted > 0


# ── Configuration Management ──────────────────────────────────────────────────

SETTING_KEY_ROUTING_THRESHOLD = "domain_routing_confidence_threshold"
SETTING_KEY_ROUTING_ENABLED = "domain_routing_enabled"


def get_domain_routing_config(db: Session) -> dict:
    """Get domain routing settings and status."""
    from app.models.system_setting import SystemSetting

    # Read dynamic threshold if set
    threshold_row = db.query(SystemSetting).filter(
        SystemSetting.key == SETTING_KEY_ROUTING_THRESHOLD
    ).first()
    threshold = (
        float(threshold_row.value)
        if threshold_row and threshold_row.value
        else settings.domain_routing_confidence_threshold
    )

    enabled_row = db.query(SystemSetting).filter(
        SystemSetting.key == SETTING_KEY_ROUTING_ENABLED
    ).first()
    enabled = (
        enabled_row.value.lower() == "true"
        if enabled_row and enabled_row.value
        else settings.domain_routing_enabled
    )

    active_domains_cnt = db.query(Domain).filter(Domain.is_active.is_(True)).count()
    configured_managers_cnt = (
        db.query(DomainRoutingConfig)
        .filter(DomainRoutingConfig.is_active.is_(True))
        .count()
    )

    return {
        "domain_routing_enabled": enabled,
        "domain_routing_confidence_threshold": threshold,
        "domain_routing_llm_enabled": settings.domain_routing_llm_enabled,
        "domain_routing_triage_admin_role": settings.domain_routing_triage_admin_role,
        "active_domains_count": active_domains_cnt,
        "configured_managers_count": configured_managers_cnt,
    }


def update_domain_routing_config(
    db: Session,
    update: dict,
    admin_user_id: Optional[str] = None,
) -> dict:
    """Update domain routing settings in database."""
    from app.models.system_setting import SystemSetting

    if "domain_routing_confidence_threshold" in update and update["domain_routing_confidence_threshold"] is not None:
        val = str(update["domain_routing_confidence_threshold"])
        row = db.query(SystemSetting).filter(
            SystemSetting.key == SETTING_KEY_ROUTING_THRESHOLD
        ).first()
        if row:
            row.value = val
            row.updated_by = admin_user_id
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = SystemSetting(
                key=SETTING_KEY_ROUTING_THRESHOLD,
                value=val,
                description="Minimum confidence score required to auto-route ticket without triage",
                updated_by=admin_user_id,
            )
            db.add(row)
        settings.domain_routing_confidence_threshold = update["domain_routing_confidence_threshold"]

    if "domain_routing_enabled" in update and update["domain_routing_enabled"] is not None:
        val = "true" if update["domain_routing_enabled"] else "false"
        row = db.query(SystemSetting).filter(
            SystemSetting.key == SETTING_KEY_ROUTING_ENABLED
        ).first()
        if row:
            row.value = val
            row.updated_by = admin_user_id
            row.updated_at = datetime.now(timezone.utc)
        else:
            row = SystemSetting(
                key=SETTING_KEY_ROUTING_ENABLED,
                value=val,
                description="Enable/disable automatic domain-based ticket routing",
                updated_by=admin_user_id,
            )
            db.add(row)
        settings.domain_routing_enabled = update["domain_routing_enabled"]

    db.commit()
    return get_domain_routing_config(db)


# ── Rerouting / Manual Triage ─────────────────────────────────────────────────

def reroute_ticket(
    db: Session,
    ticket_id: str,
    target_domain_key: str,
    assigned_to: Optional[str] = None,
    reviewer_notes: Optional[str] = None,
    admin_user: Optional[User] = None,
) -> Optional[Ticket]:
    """Manually reroute a ticket to a specific domain."""
    ticket = db.query(Ticket).filter(Ticket.ticket_id == ticket_id).first()
    if not ticket:
        return None

    domain = (
        db.query(Domain)
        .filter(Domain.key == target_domain_key.lower().strip(), Domain.is_active.is_(True))
        .first()
    )
    if not domain:
        return None

    now = datetime.now(timezone.utc)
    ticket.routed_domain_id = domain.id
    ticket.domain = domain.key
    ticket.status = TicketStatus.ROUTED.value
    ticket.needs_triage = False
    ticket.routing_method = "manual_admin"
    ticket.routing_confidence = 1.0
    ticket.routing_timestamp = now
    ticket.updated_at = now

    if assigned_to:
        ticket.assigned_to = assigned_to
        ticket.assigned_at = now
    else:
        managers = get_domain_managers(db, domain.id)
        if managers:
            ticket.assigned_to = str(managers[0].id)
            ticket.assigned_at = now

    if reviewer_notes:
        ticket.feedback = (
            f"{ticket.feedback}\n[Reroute] {reviewer_notes}"
            if ticket.feedback else f"[Reroute] {reviewer_notes}"
        )

    db.commit()
    db.refresh(ticket)

    # Log audit event
    _log_routing_audit(
        db,
        ticket,
        DomainRoutingResult(
            domain_key=domain.key,
            domain_id=domain.id,
            confidence=1.0,
            method="manual_admin",
            needs_triage=False,
            reasoning=f"Admin manually rerouted ticket to '{domain.name}' ({reviewer_notes or 'no notes'}).",
        ),
    )

    logger.info(
        "[DomainRouter] 🔀 Ticket %s manually rerouted to domain '%s' by admin",
        ticket_id, domain.key,
    )
    return ticket

