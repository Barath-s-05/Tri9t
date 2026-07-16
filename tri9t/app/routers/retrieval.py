"""Search and retrieval router (placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.get("/search")
async def search_nodes() -> dict[str, str]:
    """Search across document nodes (Stage 3+).

    Returns:
        Placeholder response.
    """
    return {"message": "Retrieval endpoint — not yet implemented"}
