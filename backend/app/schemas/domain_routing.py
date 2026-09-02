"""
Pydantic Schemas for Domain-Based Ticket Routing (Phase 11).
------------------------------------------------------------
Includes schemas for:
- Domain manager assignment & listing
- Domain routing configuration & thresholds
- Domain classification requests & responses
- Ticket rerouting / triage requests
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class DomainManagerOut(BaseModel):
    """Information about a domain manager/expert."""
    id: str
    domain_id: str
    domain_key: Optional[str] = None
    domain_name: Optional[str] = None
    manager_user_id: str
    manager_email: Optional[str] = None
    manager_name: Optional[str] = None
    manager_role: Optional[str] = None
    is_primary_manager: bool = False
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("id", "domain_id", "manager_user_id", mode="before")
    @classmethod
    def _stringify_uuid(cls, v: object) -> str:
        return str(v) if v is not None else ""


class DomainManagerAssignRequest(BaseModel):
    """Request to assign a user as domain manager/expert."""
    user_id: str = Field(..., description="User ID of the domain manager/expert")
    is_primary_manager: bool = Field(False, description="Whether this user is the primary manager for the domain")


class DomainRoutingConfigResponse(BaseModel):
    """Current domain routing configuration."""
    domain_routing_enabled: bool
    domain_routing_confidence_threshold: float
    domain_routing_llm_enabled: bool
    domain_routing_triage_admin_role: str
    active_domains_count: int
    configured_managers_count: int


class DomainRoutingConfigUpdateRequest(BaseModel):
    """Request to update domain routing settings (Admin only)."""
    domain_routing_enabled: Optional[bool] = Field(None, description="Master enable/disable switch")
    domain_routing_confidence_threshold: Optional[float] = Field(
        None, ge=0.0, le=1.0, description="Minimum confidence score required to auto-route (otherwise NEEDS_TRIAGE)"
    )
    domain_routing_llm_enabled: Optional[bool] = Field(None, description="Enable/disable LLM fallback classification")
    domain_routing_triage_admin_role: Optional[str] = Field(None, description="Role of admin receiving triage tickets")


class DomainClassifyRequest(BaseModel):
    """Request to classify a query into an organizational domain."""
    query_text: str = Field(..., description="Query text to classify")
    user_id: Optional[str] = Field(None, description="Optional user ID for assigned-domain heuristic")
    intent: Optional[str] = Field(None, description="Optional intent from query intelligence")
    entities: Optional[List[str]] = Field(default_factory=list, description="Optional extracted named entities")
    source_document_ids: Optional[List[str]] = Field(default_factory=list, description="Optional source document IDs")
    explicit_domain: Optional[str] = Field(None, description="Explicitly specified domain key")


class DomainClassifyResponse(BaseModel):
    """Result of domain classification."""
    domain_key: Optional[str] = None
    domain_name: Optional[str] = None
    domain_id: Optional[str] = None
    confidence: float
    method: str
    needs_triage: bool
    reasoning: str


class TicketRerouteRequest(BaseModel):
    """Request to manually reroute a ticket to a domain."""
    domain_key: str = Field(..., description="Target domain key (e.g. 'hr', 'finance', 'it')")
    assigned_to: Optional[str] = Field(None, description="Optional specific user ID to assign to")
    reviewer_notes: Optional[str] = Field(None, description="Notes on why the ticket was rerouted")
