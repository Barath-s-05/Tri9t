"""Health check endpoint."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import text

from tri9t.app.core.config import settings
from tri9t.app.db.database import SessionLocal
from tri9t.app.state import get_uptime

router = APIRouter(tags=["health"])


class ServicesStatus(BaseModel):
    """Status of individual backing services."""

    sqlite: str = Field(
        ...,
        description="SQLite connectivity status",
        examples=["connected"],
    )
    mongodb: str = Field(
        ...,
        description="MongoDB connectivity status",
        examples=["connected"],
    )
    groq: str = Field(
        ...,
        description="Groq API configuration status",
        examples=["configured"],
    )


class HealthResponse(BaseModel):
    """Detailed health response for the health check endpoint."""

    status: str = Field(
        ...,
        description="Overall application health status",
        examples=["healthy"],
    )
    version: str = Field(
        ...,
        description="Application version",
        examples=["0.1.0"],
    )
    uptime_seconds: float = Field(
        ...,
        description="Seconds since application startup",
        examples=[1234.56],
        ge=0,
    )
    services: ServicesStatus = Field(
        ...,
        description="Health status of individual backing services",
    )
    timestamp: str = Field(
        ...,
        description="Current UTC timestamp in ISO-8601 format",
        examples=["2026-07-16T15:42:18Z"],
    )


def _check_sqlite() -> str:
    """Return SQLite status via a lightweight query."""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return "connected"
        finally:
            db.close()
    except Exception:
        return "unavailable"


def _check_mongodb() -> str:
    """Return MongoDB status using the existing ping helper."""
    try:
        from tri9t.app.db.mongo import ping

        return "connected" if ping() else "unavailable"
    except Exception:
        return "unavailable"


def _check_groq() -> str:
    """Return Groq configuration status without making network calls."""
    return "configured" if settings.GROQ_API_KEY else "not_configured"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Detailed health check",
    description=(
        "Returns the current health status of the API including "
        "uptime, version, and connectivity checks for SQLite, "
        "MongoDB, and Groq configuration."
    ),
    response_description="Detailed health status object.",
)
def health_check() -> HealthResponse:
    """Return detailed application health status.

    Checks SQLite and MongoDB connectivity and verifies Groq API key
    configuration. Returns HTTP 200 regardless of individual service
    availability — callers should inspect the ``services`` object
    to determine which components are reachable.

    Returns:
        A ``HealthResponse`` with status, version, uptime, service
        checks, and a UTC timestamp.
    """
    return HealthResponse(
        status="healthy",
        version=settings.APP_VERSION,
        uptime_seconds=round(get_uptime(), 2),
        services=ServicesStatus(
            sqlite=_check_sqlite(),
            mongodb=_check_mongodb(),
            groq=_check_groq(),
        ),
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
