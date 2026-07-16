"""Search and retrieval API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.search_service import search_nodes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieval"])


@router.get("/search")
def search_document_nodes(
    query: str = Query(..., description="Search query"),
    version_id: str | None = Query(None, description="Restrict to version"),
    document_id: str | None = Query(None, description="Restrict to document"),
    impact_level: str | None = Query(None, description="Restrict to impact level"),
    db: Session = Depends(get_db),
) -> dict:
    """Search across document nodes.

    Results are deduplicated by logical_node_id and returned in
    relevance-score order.
    """
    results = search_nodes(
        db,
        query=query,
        version_id=version_id,
        document_id=document_id,
        impact_level=impact_level,
    )
    return {"results": results, "total": len(results)}
