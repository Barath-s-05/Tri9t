"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check() -> dict[str, str]:
    """Return application health status.

    Returns:
        A dictionary with ``status`` set to ``healthy``.
    """
    return {"status": "healthy"}
