"""
Chunk Access Service  –  Domain-Aware Chunk Access Control (Retrieval)
----------------------------------------------------------------------------
This is the security-critical module for the whole RAG pipeline: it decides
which chunks an authenticated user is allowed to receive, and it is the ONE
place that decision is made. Every retrieval path — vector, BM25, graph,
hybrid, Evidence Verification's independent re-retrieval, and the raw
POST /chunks/search endpoint — must go through this module. No chunk may
reach Context Fusion or the LLM without having passed it.

  User Question
       v
  Authenticated User -> Role + Permissions + Domain   (build_chunk_access_context)
       v
  Query Intelligence
       v
  Vector / BM25 / Graph Retrieval   -- fast, in-loop filtering using
       |                               ChunkAccessContext.is_authorized()
       |                               against cached/embedded metadata
       v                               (FAISS metadata, denormalized Chunk
  Authorization Filter               columns) -- an OPTIMIZATION, not the
       |                               authority.
       v
  Allowed Chunks Only  <-- filter_authorized_results() is the AUTHORITATIVE
       v                   gate: it re-checks every surviving candidate
  Context Fusion            against Document's CURRENT domain_id/visibility
       v                   in Postgres (one batched query), never trusting
  LLM                      a chunk's possibly-stale cached copy. This also
       v                   means chunks indexed before this module existed
  Evidence Verification    (no domain_id/visibility in their FAISS metadata)
       v                   are still correctly authorized — the fast path
  Answer                   just can't skip them early.

Two-layer design, matching "filtering should happen as early as
practically possible" + "do not rely only on post-retrieval filtering":
  1. Fast filter (this module's `is_authorized`, called with whatever
     domain_id/visibility a retrieval backend already has on hand) prunes
     obviously-unauthorized candidates DURING the vector/BM25/graph scan,
     before they even count toward top_k — critical, because otherwise an
     unauthorized document's chunks could crowd out authorized ones in a
     fixed-size result window (the HR/Finance example in the spec).
  2. Authoritative filter (`filter_authorized_results`) re-verifies the
     final candidate list against Postgres truth right before it's
     returned to the caller — the hard guarantee that nothing unauthorized
     escapes, independent of what any individual backend's fast filter did.

Authorization rule (mirrors app/services/document_access_service.py's
document-registry rule, applied here to retrieval instead of listing):
  - SUPER_ADMIN / PLATFORM_OWNER (domain-unrestricted): see everything.
  - visibility="global": everyone sees it.
  - visibility="domain": only users sharing the document's domain.
  - visibility="restricted": only the document's owner/uploader, or a user/
    role with an explicit DocumentAccessGrant.
  - Missing/unrecognized visibility, or a domain-scoped user with no domains
    at all: fails CLOSED (denied), never open.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.core.permissions import Role
from app.models.document import Document
from app.models.document_access import DocumentAccessGrant
from app.models.user import User
from app.services.domain_service import get_user_domain_ids, is_domain_unrestricted

logger = logging.getLogger(__name__)


@dataclass
class ChunkAccessContext:
    """
    Precomputed, per-request authorization state — built ONCE (see
    build_chunk_access_context) and threaded through the whole retrieval
    call graph, so no retrieval backend ever issues its own per-chunk
    authorization query (which would be an N+1 query storm on a hot path).
    """
    user_id: str
    role: Role
    is_unrestricted: bool
    domain_ids: Set[str] = field(default_factory=set)
    # Documents this user may see even at visibility="restricted": owned,
    # uploaded, or explicitly granted (by user_id or by role).
    restricted_document_ids: Set[str] = field(default_factory=set)

    def is_authorized(
        self, document_id: Optional[str], domain_id: Optional[str], visibility: Optional[str],
    ) -> bool:
        if self.is_unrestricted:
            return True
        v = visibility or "domain"   # Document.visibility defaults to "domain"; treat unset the same
        if v == "global":
            return True
        if v == "domain":
            return domain_id is not None and str(domain_id) in self.domain_ids
        if v == "restricted":
            return document_id is not None and document_id in self.restricted_document_ids
        # Unrecognized visibility value — fail closed, never open.
        return False

    def as_filter_fn(self) -> Callable[[dict], bool]:
        """Adapts is_authorized() to the {document_id,domain_id,visibility} metadata-dict
        shape used by vector_store/bm25_retriever's in-loop filter_fn hook."""
        def _fn(meta: dict) -> bool:
            return self.is_authorized(meta.get("document_id"), meta.get("domain_id"), meta.get("visibility"))
        return _fn


def build_chunk_access_context(db: Session, user: User, role: Role) -> ChunkAccessContext:
    is_unrestricted = is_domain_unrestricted(role)
    if is_unrestricted:
        return ChunkAccessContext(user_id=str(user.id), role=role, is_unrestricted=True)

    domain_ids = get_user_domain_ids(db, user.id)

    restricted_ids: Set[str] = set()
    owned_or_uploaded = (
        db.query(Document.document_id)
        .filter((Document.owner_id == user.id) | (Document.uploaded_by_id == user.id))
        .all()
    )
    restricted_ids.update(r[0] for r in owned_or_uploaded)
    granted = (
        db.query(DocumentAccessGrant.document_id)
        .filter((DocumentAccessGrant.user_id == user.id) | (DocumentAccessGrant.role == role.value))
        .all()
    )
    restricted_ids.update(r[0] for r in granted)

    return ChunkAccessContext(
        user_id=str(user.id), role=role, is_unrestricted=False,
        domain_ids=domain_ids, restricted_document_ids=restricted_ids,
    )


def filter_authorized_results(db: Session, results: List[dict], ctx: ChunkAccessContext) -> List[dict]:
    """
    THE authoritative gate. Re-checks every result's document against
    Document's CURRENT domain_id/visibility in Postgres — one batched
    query — rather than trusting each result's (possibly absent or stale)
    embedded domain_id/visibility. Every caller that hands chunks to
    Context Fusion, the LLM, or an API response MUST call this last.
    """
    if ctx.is_unrestricted or not results:
        return results

    doc_ids = {r["document_id"] for r in results if r.get("document_id")}
    if not doc_ids:
        return []

    rows = (
        db.query(Document.document_id, Document.domain_id, Document.visibility)
        .filter(Document.document_id.in_(doc_ids))
        .all()
    )
    truth: Dict[str, tuple] = {
        doc_id: (str(domain_id) if domain_id else None, visibility)
        for doc_id, domain_id, visibility in rows
    }

    authorized: List[dict] = []
    dropped = 0
    for r in results:
        doc_id = r.get("document_id")
        entry = truth.get(doc_id)
        if entry is None:
            dropped += 1   # document row vanished/unreadable -> fail closed
            continue
        domain_id, visibility = entry
        if ctx.is_authorized(doc_id, domain_id, visibility):
            authorized.append(r)
        else:
            dropped += 1

    if dropped:
        logger.info(
            "[ChunkAccess] 🔒 Authorization filter: dropped %d/%d unauthorized chunk(s) for user=%s role=%s",
            dropped, len(results), ctx.user_id, ctx.role.value,
        )
    return authorized
