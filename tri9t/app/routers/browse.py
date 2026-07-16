"""Document browsing router (placeholder)."""

from fastapi import APIRouter

router = APIRouter(prefix="/browse", tags=["browse"])


@router.get("/documents")
async def list_documents() -> dict[str, str]:
    """List documents and their versions (Stage 2+).

    Returns:
        Placeholder response.
    """
    return {"message": "Browse endpoint — not yet implemented"}


@router.get("/tree/{document_version_id}")
async def get_tree(document_version_id: str) -> dict[str, str]:
    """Get the hierarchical tree for a document version (Stage 2+).

    Returns:
        Placeholder response.
    """
    return {"message": f"Tree for {document_version_id} — not yet implemented"}
