"""System metrics endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.models.selection import Selection

router = APIRouter(tags=["metrics"])


class MetricsResponse(BaseModel):
    """System-wide resource counts."""

    documents: int = Field(..., description="Total number of documents", examples=[42])
    versions: int = Field(..., description="Total number of document versions", examples=[87])
    nodes: int = Field(..., description="Total number of tree nodes", examples=[1523])
    selections: int = Field(..., description="Total number of selections", examples=[12])
    generations: int = Field(
        ...,
        description="Total number of generations (from MongoDB, 0 if unavailable)",
        examples=[36],
    )


def _count_generations() -> int:
    """Count generation documents from MongoDB."""
    try:
        from tri9t.app.db.mongo import get_generations_collection

        return get_generations_collection().estimated_document_count()
    except Exception:
        return 0


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="System metrics",
    description=(
        "Returns aggregate counts of all major resource types. "
        "Generation count comes from MongoDB; all others from SQLite."
    ),
    response_description="Resource counts.",
)
def get_metrics(db: Session = Depends(get_db)) -> MetricsResponse:
    """Return system-wide resource counts.

    Returns:
        ``MetricsResponse`` with counts for documents, versions,
        nodes, selections, and generations.
    """
    return MetricsResponse(
        documents=db.query(Document).count(),
        versions=db.query(DocumentVersion).count(),
        nodes=db.query(Node).count(),
        selections=db.query(Selection).count(),
        generations=_count_generations(),
    )
