"""Shared API schemas, error helpers, and OpenAPI response templates.

This module provides:
- ``ErrorResponse`` model for all structured error responses.
- ``validate_uuid`` helper that raises 422 with a structured body.
- Factory functions for common HTTP errors (404, 422, 503).
- Pre-built OpenAPI response templates for consistent Swagger docs.
"""

from __future__ import annotations

import re

from fastapi import HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# UUID validation
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def validate_uuid(value: str, param_name: str = "id") -> str:
    """Validate that *value* is a UUID and raise 422 if not.

    Args:
        value: The raw string to check.
        param_name: Human-readable name for the parameter (used in the
            error message so the caller knows which field is wrong).

    Returns:
        The original *value* unchanged (allows inline usage).

    Raises:
        HTTPException: 422 when *value* is not a valid UUID.
    """
    if not _UUID_RE.match(value):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "InvalidUUID",
                "message": (
                    f"'{value}' is not a valid UUID for parameter "
                    f"'{param_name}'."
                ),
                "hint": (
                    "Provide a standard UUID v4 string "
                    "(e.g. '550e8400-e29b-41d4-a716-446655440000')."
                ),
            },
        )
    return value


# ---------------------------------------------------------------------------
# Structured error factories
# ---------------------------------------------------------------------------


def not_found_error(
    resource: str,
    resource_id: str,
    hint: str | None = None,
) -> HTTPException:
    """Return a 404 ``HTTPException`` with a structured body.

    Args:
        resource: Resource type name (e.g. ``"Document"``).
        resource_id: The identifier that was looked up.
        hint: Optional next-step suggestion.
    """
    return HTTPException(
        status_code=404,
        detail={
            "error": f"{resource}NotFound",
            "message": f"{resource} '{resource_id}' was not found.",
            "hint": hint,
        },
    )


def validation_error(
    error: str,
    message: str,
    hint: str | None = None,
) -> HTTPException:
    """Return a 422 ``HTTPException`` with a structured body.

    Args:
        error: Machine-readable error code.
        message: Human-readable description.
        hint: Optional next-step suggestion.
    """
    return HTTPException(
        status_code=422,
        detail={
            "error": error,
            "message": message,
            "hint": hint,
        },
    )


def service_unavailable(
    message: str,
    hint: str | None = None,
) -> HTTPException:
    """Return a 503 ``HTTPException`` with a structured body.

    Args:
        message: Human-readable description.
        hint: Optional next-step suggestion.
    """
    return HTTPException(
        status_code=503,
        detail={
            "error": "ServiceUnavailable",
            "message": message,
            "hint": hint,
        },
    )


def internal_error(
    message: str,
    hint: str | None = None,
) -> HTTPException:
    """Return a 500 ``HTTPException`` with a structured body.

    Args:
        message: Human-readable description.
        hint: Optional next-step suggestion.
    """
    return HTTPException(
        status_code=500,
        detail={
            "error": "InternalServerError",
            "message": message,
            "hint": hint,
        },
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Structured error response returned by all endpoints on failure."""

    error: str = Field(
        ...,
        description="Machine-readable error code",
        examples=["NotFound"],
    )
    message: str = Field(
        ...,
        description="Human-readable error message",
        examples=["Document '550e8400-e29b-41d4-a716-446655440000' was not found."],
    )
    hint: str | None = Field(
        None,
        description="Suggested action to resolve the error",
        examples=["Use GET /documents to list available documents."],
    )


class SuccessResponse(BaseModel):
    """Generic success response with a message."""

    message: str = Field(
        ...,
        description="Human-readable success message",
        examples=["Selection deleted successfully."],
    )


# ---------------------------------------------------------------------------
# OpenAPI response templates (status-code keyed for FastAPI responses=)
# ---------------------------------------------------------------------------

ERROR_RESPONSE_NOT_FOUND: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Resource not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "DocumentNotFound",
                    "message": "Document '550e8400-...' was not found.",
                    "hint": "Use GET /documents to list available documents.",
                }
            }
        },
    },
}

ERROR_RESPONSE_INVALID_UUID: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Invalid UUID format",
        "content": {
            "application/json": {
                "example": {
                    "error": "InvalidUUID",
                    "message": "'abc' is not a valid UUID for parameter 'document_id'.",
                    "hint": "Provide a standard UUID v4 string.",
                }
            }
        },
    },
}

ERROR_RESPONSE_VALIDATION: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Validation error",
        "content": {
            "application/json": {
                "example": {
                    "error": "EmptySearchQuery",
                    "message": "Search query cannot be empty.",
                    "hint": "Provide a non-empty search query string.",
                }
            }
        },
    },
}

ERROR_RESPONSE_SERVICE_UNAVAILABLE: dict[int, dict] = {
    503: {
        "model": ErrorResponse,
        "description": "Service unavailable",
        "content": {
            "application/json": {
                "example": {
                    "error": "ServiceUnavailable",
                    "message": "Groq API key not configured.",
                    "hint": "Set the GROQ_API_KEY environment variable.",
                }
            }
        },
    },
}


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------

class PaginationMeta(BaseModel):
    """Pagination metadata returned with every paginated list response."""

    page: int = Field(..., description="Current page number (1-based)", examples=[1], ge=1)
    limit: int = Field(..., description="Items per page", examples=[20], ge=1)
    total: int = Field(..., description="Total number of items matching the query", examples=[145], ge=0)
    pages: int = Field(..., description="Total number of pages", examples=[8], ge=0)


def paginate(items: list, page: int, limit: int) -> tuple[list, PaginationMeta]:
    """Slice a list and return items + pagination metadata.

    Args:
        items: Full list of items.
        page: 1-based page number.
        limit: Items per page.

    Returns:
        Tuple of (sliced items, PaginationMeta).
    """
    total = len(items)
    pages = max(1, (total + limit - 1) // limit) if limit > 0 else 1
    start = (page - 1) * limit
    end = start + limit
    return items[start:end], PaginationMeta(
        page=page,
        limit=limit,
        total=total,
        pages=pages,
    )


# ---------------------------------------------------------------------------
# Shared pagination query parameter descriptions
# ---------------------------------------------------------------------------

pagination_params = {
    "page": (1, "Page number (1-based)"),
    "limit": (20, "Items per page (1-100)"),
}
