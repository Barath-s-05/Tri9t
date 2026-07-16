"""Health check endpoint."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Response model for the health check endpoint."""

    status: str = Field(
        ...,
        description="Application health status",
        examples=["healthy"],
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns the current health status of the API.",
    response_description="Health status object.",
)
def health_check() -> HealthResponse:
    """Return application health status.

    Use this endpoint to verify the API is running and responsive.
    Returns ``{"status": "healthy"}`` when the service is operational.

    Returns:
        A ``HealthResponse`` with ``status`` set to ``healthy``.
    """
    return HealthResponse(status="healthy")
