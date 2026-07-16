"""Node selection router (placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/selections", tags=["selections"])


@router.post("/")
async def create_selection() -> dict[str, str]:
    """Pin a node to a document version (Stage 3+).

    Returns:
        Placeholder response.
    """
    return {"message": "Selection endpoint — not yet implemented"}
