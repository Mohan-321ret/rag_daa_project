"""
Graph Service (Neo4j)
----------------------
Thin wrapper around the Neo4j Python driver.
Provides session management and basic CRUD helpers for knowledge graph operations.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from neo4j import GraphDatabase, Driver
from app.core.config import settings


class Neo4jService:
    """Manages Neo4j driver lifecycle and query execution."""

    def __init__(self):
        self._driver: Optional[Driver] = None

    # ── Connection ────────────────────────────────────────────────────────────

    def connect(self) -> None:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            self._driver.verify_connectivity()

    def close(self) -> None:
        if self._driver:
            self._driver.close()
            self._driver = None

    @contextmanager
    def session(self) -> Generator:
        self.connect()
        with self._driver.session() as s:
            yield s

    def is_connected(self) -> bool:
        try:
            self.connect()
            return True
        except Exception:
            return False

    # ── Generic Query ─────────────────────────────────────────────────────────

    def run(self, cypher: str, params: dict | None = None) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return a list of record dicts."""
        with self.session() as s:
            result = s.run(cypher, params or {})
            return [dict(r) for r in result]

    # ── Node Helpers ──────────────────────────────────────────────────────────

    def create_node(self, label: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Create a node and return its properties."""
        cypher = f"CREATE (n:{label} $props) RETURN n"
        records = self.run(cypher, {"props": properties})
        return dict(records[0]["n"]) if records else {}

    def find_nodes(self, label: str, filters: Dict[str, Any] | None = None) -> List[Dict]:
        """Find nodes matching optional property filters."""
        where = ""
        if filters:
            conditions = " AND ".join(f"n.{k} = ${k}" for k in filters)
            where = f" WHERE {conditions}"
        cypher = f"MATCH (n:{label}){where} RETURN n LIMIT 100"
        records = self.run(cypher, filters or {})
        return [dict(r["n"]) for r in records]

    # ── Relationship Helpers ──────────────────────────────────────────────────

    def create_relationship(
        self,
        from_label: str,
        from_props: dict,
        rel_type: str,
        to_label: str,
        to_props: dict,
        rel_props: dict | None = None,
    ) -> bool:
        """
        MERGE both nodes then create the relationship between them.
        Returns True on success.
        """
        cypher = (
            f"MERGE (a:{from_label} $from_props) "
            f"MERGE (b:{to_label} $to_props) "
            f"MERGE (a)-[r:{rel_type} $rel_props]->(b) "
            "RETURN r"
        )
        records = self.run(
            cypher,
            {
                "from_props": from_props,
                "to_props": to_props,
                "rel_props": rel_props or {},
            },
        )
        return len(records) > 0


# ── Singleton ─────────────────────────────────────────────────────────────────
_graph_service: Neo4jService | None = None


def get_graph_service() -> Neo4jService:
    global _graph_service
    if _graph_service is None:
        _graph_service = Neo4jService()
    return _graph_service
