"""Document ingestion router (placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/documents")
async def ingest_document() -> dict[str, str]:
    """Upload and parse a PDF document (Stage 2+).

    Returns:
        Placeholder response.
    """
    return {"message": "Ingestion endpoint — not yet implemented"}
