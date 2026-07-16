"""Search and retrieval API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.schemas.api import (
    ERROR_RESPONSE_INVALID_UUID,
    ErrorResponse,
    pagination_params,
    validation_error,
    validate_uuid,
)
from tri9t.app.services.search_service import search_nodes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["retrieval"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class SearchResultItem(BaseModel):
    """A single search result with relevance scoring."""

    node_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    heading: str = Field(..., examples=["1.2 Battery Safety"])
    level: int = Field(..., examples=[2])
    section_number: str | None = Field(None, examples=["1.2"])
    body_text: str = Field(..., examples=["Battery voltage must not exceed..."])
    logical_node_id: str | None = Field(None)
    version_id: str | None = Field(None)
    document_id: str = Field(..., examples=["550e8400-..."])
    content_hash: str = Field(..., examples=["abc123..."])
    page_number: int | None = Field(None, examples=[5])
    change_status: str | None = Field(None, examples=["modified"])
    impact_level: str | None = Field(None, examples=["HIGH"])
    score: float = Field(..., description="Relevance score (0.0-1.0)", examples=[0.85])
    match_type: str = Field(
        ...,
        description="How the node matched the query",
        examples=["exact_heading"],
    )


class SearchResponse(BaseModel):
    """Response for the search endpoint."""

    results: list[SearchResultItem] = Field(
        ...,
        description="Search results ordered by relevance score descending",
    )
    total: int = Field(
        ...,
        description="Number of results returned",
        examples=[5],
    )
    page: int = Field(..., description="Current page number", examples=[1])
    limit: int = Field(..., description="Items per page", examples=[20])
    pages: int = Field(..., description="Total number of pages", examples=[1])


class EmptyQueryError(BaseModel):
    """Error response for empty search queries."""

    error: str = Field(..., examples=["EmptySearchQuery"])
    message: str = Field(..., examples=["Search query cannot be empty."])
    hint: str | None = Field(
        None,
        examples=["Provide a non-empty search query string."],
    )


# ---------------------------------------------------------------------------
# OpenAPI response configs
# ---------------------------------------------------------------------------

_DOCS_422_EMPTY_QUERY: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Empty or whitespace-only search query",
        "content": {
            "application/json": {
                "example": {
                    "error": "EmptySearchQuery",
                    "message": "Search query cannot be empty or whitespace-only.",
                    "hint": "Provide a non-empty search query string.",
                }
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search document nodes",
    description=(
        "Search across all document nodes using multi-factor relevance "
        "scoring. Results are deduplicated by logical node ID and "
        "returned in descending score order. Supports heading, body text, "
        "and section number matching."
    ),
    response_description="Ranked search results with relevance scores.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_422_EMPTY_QUERY,
    },
)
def search_document_nodes(
    query: str = Query(
        ...,
        description="Search query string (at least 1 character). "
        "Matches against headings, body text, and section numbers.",
        examples=["battery safety"],
    ),
    version_id: str | None = Query(
        None,
        description="Restrict results to a specific document version UUID",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    document_id: str | None = Query(
        None,
        description="Restrict results to a specific document UUID",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    impact_level: str | None = Query(
        None,
        description="Restrict results to a specific impact level "
        "(LOW, MEDIUM, HIGH, CRITICAL)",
        examples=["HIGH"],
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)", examples=[1]),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)", examples=[20]),
    sort: str | None = Query(
        None,
        description="Field to sort by (score, heading, created_at)",
        examples=["score"],
    ),
    order: str = Query("desc", description="Sort order: asc or desc", examples=["desc"]),
    db: Session = Depends(get_db),
) -> SearchResponse:
    """Search across document nodes.

    Results are deduplicated by ``logical_node_id`` and returned in
    relevance-score order.

    Args:
        query: Non-empty search query string.
        version_id: Optional version UUID to scope results.
        document_id: Optional document UUID to scope results.
        impact_level: Optional impact level filter.

    Returns:
        ``SearchResponse`` with ranked results and total count.

    Raises:
        422: If the query is empty/whitespace or a UUID parameter is invalid.
    """
    if not query or not query.strip():
        raise validation_error(
            "EmptySearchQuery",
            "Search query cannot be empty or whitespace-only.",
            "Provide a non-empty search query string.",
        )

    if version_id is not None:
        validate_uuid(version_id, "version_id")
    if document_id is not None:
        validate_uuid(document_id, "document_id")

    if impact_level is not None:
        valid_levels = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
        if impact_level.upper() not in valid_levels:
            raise validation_error(
                "InvalidImpactLevel",
                f"'{impact_level}' is not a valid impact level.",
                f"Use one of: {', '.join(sorted(valid_levels))}.",
            )

    results = search_nodes(
        db,
        query=query.strip(),
        version_id=version_id,
        document_id=document_id,
        impact_level=impact_level,
    )

    logger.info(
        "Search '%s': %d results (version=%s, document=%s)",
        query.strip(),
        len(results),
        version_id,
        document_id,
    )

    total = len(results)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    page_results = results[start : start + limit]

    return SearchResponse(
        results=page_results,
        total=total,
        page=page,
        limit=limit,
        pages=pages,
    )
