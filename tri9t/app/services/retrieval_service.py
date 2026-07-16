"""Enhanced retrieval service for generations.

Provides enriched generation retrieval with staleness information,
node-based generation lookup, and selection-based generation lookup.
All MongoDB queries are isolated here; the router stays thin.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from tri9t.app.db.mongo import get_generations_collection
from tri9t.app.services.staleness_service import check_staleness

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_generation_with_staleness(
    db: Session,
    generation_id: str,
) -> dict[str, Any] | None:
    """Fetch a generation and attach staleness information.

    Combines the generation document from MongoDB with a live
    staleness check against the current SQLite state.

    Args:
        db: Active SQLAlchemy session.
        generation_id: The generation UUID.

    Returns:
        Enriched generation dict with ``staleness`` key, or None.
    """
    try:
        doc = get_generations_collection().find_one(
            {"_id": generation_id}, {"_id": 0}
        )
    except Exception as exc:
        logger.error("MongoDB read failed: %s", exc)
        return None

    if doc is None:
        return None

    staleness = check_staleness(db, generation_id)
    doc["staleness"] = staleness.to_dict()
    return doc


def get_generations_for_node(
    node_id: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return all generations that included a specific node.

    Searches MongoDB ``generations`` collection for documents
    where ``node_ids`` (stored in the selection) contained the
    given node.  Since generations store ``selection_id`` but not
    ``node_ids`` directly, we look up the selection first.

    Args:
        node_id: The node ID to search for.
        limit: Maximum results to return.
        offset: Pagination offset.

    Returns:
        Dict with ``generations`` list and ``total`` count.
    """
    from tri9t.app.db.database import SessionLocal
    from tri9t.app.services.selection_service import get_selections

    try:
        # Find all selections that contain this node
        db = SessionLocal()
        try:
            all_selections = get_selections(db)
        finally:
            db.close()

        selection_ids = [
            s["id"]
            for s in all_selections
            if node_id in s.get("node_ids", [])
        ]

        if not selection_ids:
            return {"generations": [], "total": 0}

        # Query MongoDB for generations with these selection IDs
        col = get_generations_collection()
        query = {"selection_id": {"$in": selection_ids}}
        total = col.count_documents(query)
        docs = list(
            col.find(query, {"_id": 0})
            .sort("generated_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return {"generations": docs, "total": total}
    except Exception as exc:
        logger.error("Failed to fetch generations for node: %s", exc)
        return {"generations": [], "total": 0}


def get_generations_for_selection(
    selection_id: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return all generations for a specific selection.

    Args:
        selection_id: The selection ID.
        limit: Maximum results to return.
        offset: Pagination offset.

    Returns:
        Dict with ``generations`` list and ``total`` count.
    """
    try:
        col = get_generations_collection()
        query = {"selection_id": selection_id}
        total = col.count_documents(query)
        docs = list(
            col.find(query, {"_id": 0})
            .sort("generated_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return {"generations": docs, "total": total}
    except Exception as exc:
        logger.error("Failed to fetch generations for selection: %s", exc)
        return {"generations": [], "total": 0}
