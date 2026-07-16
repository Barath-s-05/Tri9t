"""Search service for document nodes.

Supports heading search, body text search, section number search,
version filtering, impact filtering, heading similarity, and partial
keyword matching.  Results are deduplicated by logical_node_id and
returned in relevance-score order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import or_
from sqlalchemy.orm import Session

from tri9t.app.models.document import DocumentVersion
from tri9t.app.models.node import Node

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A single search result with relevance scoring."""

    node_id: str
    heading: str
    level: int
    section_number: str | None
    body_text: str
    logical_node_id: str | None
    version_id: str | None
    document_id: str
    content_hash: str
    page_number: int | None
    change_status: str | None = None
    impact_level: str | None = None
    score: float = 0.0
    match_type: str = ""


def _heading_similarity(query: str, heading: str) -> float:
    """Case-insensitive heading similarity score.

    Args:
        query: The search query.
        heading: The node heading.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    return SequenceMatcher(None, query.lower(), heading.lower()).ratio()


def _compute_score(
    query_lower: str,
    heading: str,
    body_text: str,
    section_number: str | None,
) -> tuple[float, str]:
    """Compute relevance score and match type for a node.

    Scoring priority:
    1. Exact heading match — score 1.0
    2. Heading contains query — score 0.8 + similarity
    3. Section number match — score 0.7
    4. Body text contains query — score 0.5 + similarity
    5. Heading similarity (partial) — score based on ratio

    Args:
        query_lower: Lowercase search query.
        heading: The node heading.
        body_text: The node body text.
        section_number: Optional section number.

    Returns:
        Tuple of (score, match_type).
    """
    heading_lower = heading.lower()
    body_lower = body_text.lower() if body_text else ""

    # Exact heading match
    if heading_lower == query_lower:
        return 1.0, "exact_heading"

    # Heading contains query
    if query_lower in heading_lower:
        sim = _heading_similarity(query_lower, heading)
        return 0.8 + sim * 0.15, "heading_contains"

    # Section number exact match
    if section_number and query_lower == section_number.lower():
        return 0.75, "section_exact"

    # Section number partial
    if section_number and query_lower in section_number.lower():
        return 0.70, "section_partial"

    # Body text match
    if body_lower and query_lower in body_lower:
        sim = _heading_similarity(query_lower, body_text[:100])
        return 0.5 + sim * 0.2, "body_contains"

    # Heading similarity (fuzzy)
    sim = _heading_similarity(query_lower, heading)
    if sim > 0.5:
        return sim * 0.6, "heading_fuzzy"

    return 0.0, "no_match"


def search_nodes(
    db: Session,
    query: str,
    version_id: str | None = None,
    document_id: str | None = None,
    impact_level: str | None = None,
) -> list[dict]:
    """Search across document nodes with multi-factor relevance scoring.

    Results are deduplicated by ``logical_node_id`` (keeping the
    highest-scored occurrence) and returned in descending score order.

    Args:
        db: Active SQLAlchemy session.
        query: The search query string.
        version_id: Optional version ID to restrict results.
        document_id: Optional document ID to restrict results.
        impact_level: Optional impact level to restrict results (e.g. "critical", "high").

    Returns:
        List of result dicts ordered by score descending.
    """
    if not query or not query.strip():
        return []

    q = db.query(Node)

    if version_id:
        q = q.filter(Node.version_id == version_id)
    if document_id:
        q = q.filter(Node.document_id == document_id)
    if impact_level:
        q = q.filter(Node.impact_level == impact_level)

    nodes = q.all()
    results: list[SearchResult] = []

    for node in nodes:
        body = node.body_text or ""
        score, match_type = _compute_score(
            query.lower().strip(),
            node.heading,
            body,
            node.section_number,
        )

        if score > 0.0:
            results.append(
                SearchResult(
                    node_id=node.id,
                    heading=node.heading,
                    level=node.level,
                    section_number=node.section_number,
                    body_text=body[:500],
                    logical_node_id=node.logical_node_id,
                    version_id=node.version_id,
                    document_id=node.document_id,
                    content_hash=node.content_hash,
                    page_number=node.page_number,
                    change_status=node.change_status,
                    impact_level=node.impact_level,
                    score=round(score, 4),
                    match_type=match_type,
                )
            )

    # Deduplicate by logical_node_id, keeping highest score
    seen: dict[str, SearchResult] = {}
    for r in results:
        key = r.logical_node_id or r.node_id
        if key not in seen or r.score > seen[key].score:
            seen[key] = r

    ranked = sorted(seen.values(), key=lambda r: r.score, reverse=True)

    logger.info(
        "Search '%s': %d results (deduplicated from %d matches)",
        query,
        len(ranked),
        len(results),
    )

    return [
        {
            "node_id": r.node_id,
            "heading": r.heading,
            "level": r.level,
            "section_number": r.section_number,
            "body_text": r.body_text,
            "logical_node_id": r.logical_node_id,
            "version_id": r.version_id,
            "document_id": r.document_id,
            "content_hash": r.content_hash,
            "page_number": r.page_number,
            "change_status": r.change_status,
            "impact_level": r.impact_level,
            "score": r.score,
            "match_type": r.match_type,
        }
        for r in ranked
    ]
