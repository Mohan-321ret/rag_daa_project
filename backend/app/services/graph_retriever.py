"""
Knowledge Graph Retriever  –  Phase 8 Module 6 (Route: Relationship → Graph)
--------------------------------------------------------------------------------
Answers "how are X and Y related" style questions by walking an entity
co-occurrence graph in Neo4j, instead of nearest-neighbour vector search.

Population (lightweight, piggybacks on Phase 7's NER — NOT a full relation-
extraction system): every chunk indexed by the ingestion pipeline is also
run through spaCy NER (app.services.ner_service), and each chunk's entities
are written as:

    (:Document {document_id})
    (:Chunk {chunk_id, document_id, chunk_index})-[:PART_OF]->(:Document)
    (:Entity {name, label})-[:MENTIONED_IN]->(:Chunk)
    (:Entity)-[:CO_OCCURS_WITH]-(:Entity)   -- entities sharing a chunk

Retrieval matches the entities the Query Intelligence module (Phase 7)
already extracted from the user's QUESTION against this graph, then
returns the chunks where those entities (and anything they co-occur with)
were mentioned.

Every public method is fail-soft: if Neo4j is unreachable, ingestion and
retrieval both degrade gracefully (log + return / no-op) rather than
breaking the pipeline — the graph route simply contributes nothing to a
hybrid search rather than raising.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from app.core.config import settings
from app.services.ner_service import Entity

logger = logging.getLogger(__name__)

# Entity types worth graphing. Numeric/temporal types (DATE, CARDINAL, PERCENT,
# MONEY, TIME, QUANTITY, ORDINAL) drive the Temporal Detection step (Phase 7)
# instead — they'd otherwise flood the graph with low-value nodes.
GRAPH_ENTITY_LABELS = frozenset({
    "PERSON", "ORG", "GPE", "NORP", "FAC", "LAW", "EVENT", "PRODUCT", "WORK_OF_ART",
})


@dataclass
class GraphHit:
    document_id: str
    chunk_index: int
    matched_entity: str
    entity_label: str
    related_entities: List[str] = field(default_factory=list)
    rank: int = 0


def _chunk_id(document_id: str, chunk_index: int) -> str:
    return f"{document_id}::{chunk_index}"


class GraphRetriever:
    """Neo4j-backed entity co-occurrence graph for relationship queries."""

    def index_chunk_entities(
        self, document_id: str, chunk_index: int, entities: List[Entity],
        domain_id: Optional[str] = None, visibility: Optional[str] = None,
    ) -> None:
        """
        Upsert one chunk's graphable entities and their co-occurrence edges.
        No-ops silently if Neo4j is unreachable (ingestion must not fail).

        domain_id/visibility (Domain-Aware Document Metadata phase) are set
        as properties on the (:Document) node — PostgreSQL metadata
        propagating "to Neo4j where applicable". Informational only today:
        no graph query filters by them yet (graph retrieval isn't
        domain-scoped, same documented boundary as elsewhere in this phase).
        """
        graphable = sorted({
            (e.text.strip(), e.label) for e in entities
            if e.label in GRAPH_ENTITY_LABELS and e.text.strip()
        })
        if not graphable:
            return

        from app.services.graph_service import get_graph_service
        graph = get_graph_service()
        if not graph.is_connected():
            logger.debug("[GraphRetriever] Neo4j unavailable – skipping graph indexing.")
            return

        chunk_id = _chunk_id(document_id, chunk_index)
        try:
            graph.run(
                """
                MERGE (d:Document {document_id: $document_id})
                SET d.domain_id = $domain_id, d.visibility = $visibility
                MERGE (c:Chunk {chunk_id: $chunk_id})
                SET c.document_id = $document_id, c.chunk_index = $chunk_index
                MERGE (c)-[:PART_OF]->(d)
                WITH c
                UNWIND $entities AS ent
                MERGE (e:Entity {name: ent.name, label: ent.label})
                MERGE (e)-[:MENTIONED_IN]->(c)
                """,
                {
                    "document_id": document_id,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "entities": [{"name": n, "label": l} for n, l in graphable],
                    "domain_id": domain_id,
                    "visibility": visibility,
                },
            )
            if len(graphable) > 1:
                pairs = [
                    {"a": graphable[i][0], "b": graphable[j][0]}
                    for i in range(len(graphable))
                    for j in range(i + 1, len(graphable))
                ]
                graph.run(
                    """
                    UNWIND $pairs AS p
                    MATCH (e1:Entity {name: p.a}), (e2:Entity {name: p.b})
                    MERGE (e1)-[:CO_OCCURS_WITH]-(e2)
                    """,
                    {"pairs": pairs},
                )
        except Exception as exc:
            logger.warning("[GraphRetriever] Failed to index chunk %s: %s", chunk_id, exc)

    def remove_document(self, document_id: str) -> None:
        """
        Drop a superseded document version's chunks from the graph (Phase 6
        versioning consistency — only the latest version should be queryable).
        Entity nodes themselves are kept (other chunks/documents may still
        reference them); only this document's Chunk nodes are detached.
        """
        from app.services.graph_service import get_graph_service
        graph = get_graph_service()
        if not graph.is_connected():
            return
        try:
            graph.run(
                "MATCH (c:Chunk {document_id: $document_id}) DETACH DELETE c",
                {"document_id": document_id},
            )
        except Exception as exc:
            logger.warning(
                "[GraphRetriever] Failed to remove document %s from graph: %s",
                document_id, exc,
            )

    def search_related_chunks(self, entity_texts: List[str], top_k: int = 5) -> List[GraphHit]:
        """
        Find chunks mentioning entities matching *entity_texts* (case-insensitive
        substring match), enriched with each entity's co-occurring neighbours.
        Returns [] if Neo4j is unreachable or no entities were supplied.
        """
        if not entity_texts:
            return []

        from app.services.graph_service import get_graph_service
        graph = get_graph_service()
        if not graph.is_connected():
            logger.debug("[GraphRetriever] Neo4j unavailable – graph route returns no results.")
            return []

        try:
            records = graph.run(
                """
                UNWIND $terms AS term
                MATCH (e:Entity)
                WHERE toLower(e.name) CONTAINS toLower(term)
                OPTIONAL MATCH (e)-[:CO_OCCURS_WITH]-(related:Entity)
                OPTIONAL MATCH (e)-[:MENTIONED_IN]->(c:Chunk)
                WITH e, collect(DISTINCT related.name) AS related_entities,
                     collect(DISTINCT {document_id: c.document_id, chunk_index: c.chunk_index}) AS chunks
                RETURN e.name AS entity, e.label AS label, related_entities, chunks
                LIMIT $limit
                """,
                {"terms": entity_texts, "limit": top_k * 3},
            )
        except Exception as exc:
            logger.warning("[GraphRetriever] Search failed: %s", exc)
            return []

        hits: List[GraphHit] = []
        for rec in records:
            for chunk in rec.get("chunks") or []:
                if chunk.get("document_id") is None:
                    continue
                hits.append(GraphHit(
                    document_id=chunk["document_id"],
                    chunk_index=chunk["chunk_index"],
                    matched_entity=rec["entity"],
                    entity_label=rec["label"],
                    related_entities=[r for r in (rec.get("related_entities") or []) if r],
                ))
                if len(hits) >= top_k:
                    break
            if len(hits) >= top_k:
                break

        for rank, hit in enumerate(hits, start=1):
            hit.rank = rank

        logger.info(
            "[GraphRetriever] %d chunk(s) matched for entities=%s", len(hits), entity_texts
        )
        return hits


# ── Singleton ─────────────────────────────────────────────────────────────────
_retriever: GraphRetriever | None = None


def get_graph_retriever() -> GraphRetriever:
    global _retriever
    if _retriever is None:
        _retriever = GraphRetriever()
    return _retriever
