"""QA generation API endpoints.

Thin layer that parses requests and delegates to
``generation_service`` and ``retrieval_service``.
No business logic lives here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.schemas.api import (
    ERROR_RESPONSE_INVALID_UUID,
    ErrorResponse,
    not_found_error,
    service_unavailable,
    validation_error,
    validate_uuid,
)
from tri9t.app.services.generation_service import (
    GenerationError,
    generate_test_cases,
    get_generation,
    get_generation_history,
)
from tri9t.app.services.retrieval_service import (
    get_generation_with_staleness,
    get_generations_for_node,
    get_generations_for_selection,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generation"])

# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Body for ``POST /generate``."""

    selection_id: str = Field(
        ...,
        description="UUID of the selection to generate test cases for",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    model: str | None = Field(
        None,
        description="Override the default LLM model",
        examples=["llama-3.3-70b-versatile"],
    )
    temperature: float | None = Field(
        None,
        ge=0.0,
        le=2.0,
        description="Override the default temperature (0.0 - 2.0)",
        examples=[0.7],
    )


class GenerationMetadata(BaseModel):
    """Metadata for a completed generation."""

    selection_id: str = Field(..., examples=["550e8400-..."])
    version_id: str = Field(..., examples=["550e8400-..."])
    prompt_version: str = Field(..., examples=["1.0"])
    prompt_hash: str = Field(..., examples=["abc123..."])
    provider: str = Field(..., examples=["groq"])
    model: str = Field(..., examples=["llama-3.3-70b-versatile"])
    temperature: float = Field(..., examples=[0.7])
    generated_at: str = Field(..., examples=["2025-01-15T10:30:00Z"])
    validation_status: str = Field(..., examples=["valid"])
    retry_count: int = Field(..., examples=[0])
    response_hash: str = Field(..., examples=["def456..."])
    processing_time_ms: int = Field(..., examples=[3500])


class GenerateResponse(BaseModel):
    """Successful generation response."""

    generation_id: str = Field(
        ...,
        description="UUID of the newly created generation",
        examples=["660e8400-e29b-41d4-a716-446655440001"],
    )
    test_cases: list[dict] = Field(
        ...,
        description="Generated QA test cases",
    )
    metadata: GenerationMetadata = Field(
        ...,
        description="Generation metadata including model, timing, and prompt info",
    )


class GenerationHistoryEntry(BaseModel):
    """Summary of a generation in history view."""

    selection_id: str | None = Field(None)
    version_id: str | None = Field(None)
    model: str | None = Field(None)
    generated_at: str | None = Field(None)
    test_case_count: int | None = Field(None, examples=[3])


class GenerationHistoryResponse(BaseModel):
    """Paginated history response."""

    generations: list[dict] = Field(
        ...,
        description="List of generation records",
    )
    total: int = Field(
        ...,
        description="Total number of matching generations",
        examples=[42],
    )


class GenerationDetailResponse(BaseModel):
    """Single generation with staleness info."""

    generation_id: str | None = Field(None, alias="_id")
    test_cases: list[dict] | None = None
    staleness: dict | None = Field(
        None,
        description="Staleness status of this generation",
    )


# ---------------------------------------------------------------------------
# OpenAPI response configs
# ---------------------------------------------------------------------------

_DOCS_404_GENERATION: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Generation not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "GenerationNotFound",
                    "message": "Generation '550e8400-...' was not found.",
                    "hint": "Check the generation ID or create a new generation with POST /generate.",
                }
            }
        },
    },
}

_DOCS_422_GENERATE: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Generation validation error",
        "content": {
            "application/json": {
                "example": {
                    "error": "SelectionNotFound",
                    "message": "Selection '550e8400-...' was not found.",
                    "hint": "Create a selection first with POST /selections/.",
                }
            }
        },
    },
}

_DOCS_503: dict[int, dict] = {
    503: {
        "model": ErrorResponse,
        "description": "LLM provider unavailable",
        "content": {
            "application/json": {
                "example": {
                    "error": "ServiceUnavailable",
                    "message": "No Groq API key configured.",
                    "hint": "Set the GROQ_API_KEY environment variable.",
                }
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/generate",
    response_model=GenerateResponse,
    summary="Generate QA test cases",
    description=(
        "Trigger AI-powered QA test-case generation from a selection of "
        "document nodes. The generation is stored in MongoDB and includes "
        "staleness tracking."
    ),
    response_description="Generated test cases and metadata.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_422_GENERATE,
        **_DOCS_503,
    },
)
async def generate(
    body: GenerateRequest,
    db: Session = Depends(get_db),
) -> GenerateResponse:
    """Trigger QA test-case generation from a selection.

    Args:
        body: Generation request with selection ID and optional overrides.

    Returns:
        ``GenerateResponse`` with test cases and metadata.

    Raises:
        422: If the selection is invalid or has no nodes.
        404: If the selection does not exist.
        503: If the LLM provider is not configured.
    """
    validate_uuid(body.selection_id, "selection_id")

    if body.temperature is not None and not (0.0 <= body.temperature <= 2.0):
        raise validation_error(
            "InvalidTemperature",
            f"Temperature must be between 0.0 and 2.0, got {body.temperature}.",
            "Use a temperature value between 0.0 and 2.0.",
        )

    logger.info("Generation requested for selection %s", body.selection_id)

    try:
        result = await generate_test_cases(
            db=db,
            selection_id=body.selection_id,
            model_override=body.model,
            temperature_override=body.temperature,
        )
        return GenerateResponse(**result)
    except GenerationError as exc:
        msg = str(exc).lower()
        if "not found" in msg:
            raise not_found_error(
                "Selection",
                body.selection_id,
                "Create a selection first with POST /selections/.",
            ) from exc
        if "no nodes" in msg or "no valid nodes" in msg:
            raise validation_error(
                "EmptySelection",
                str(exc),
                "Ensure the selection contains at least one valid node.",
            ) from exc
        if "no groq api key" in msg:
            raise service_unavailable(
                str(exc),
                "Set the GROQ_API_KEY environment variable.",
            ) from exc
        raise validation_error("GenerationError", str(exc)) from exc


@router.get(
    "/generation/history",
    response_model=GenerationHistoryResponse,
    summary="List generation history",
    description=(
        "Returns a paginated list of past generations, optionally "
        "filtered by selection ID or version ID."
    ),
    response_description="Paginated generation history.",
)
async def history(
    selection_id: str | None = Query(
        None,
        description="Filter by selection UUID",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    version_id: str | None = Query(
        None,
        description="Filter by document version UUID",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of results to return (1-100)",
        examples=[20],
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Number of results to skip for pagination",
        examples=[0],
    ),
) -> GenerationHistoryResponse:
    """Return paginated generation history.

    Args:
        selection_id: Optional selection UUID to filter.
        version_id: Optional version UUID to filter.
        limit: Maximum results per page (1-100).
        offset: Pagination offset.

    Returns:
        ``GenerationHistoryResponse`` with generations and total count.
    """
    if selection_id is not None:
        validate_uuid(selection_id, "selection_id")
    if version_id is not None:
        validate_uuid(version_id, "version_id")

    result = get_generation_history(
        selection_id=selection_id,
        version_id=version_id,
        limit=limit,
        offset=offset,
    )
    return GenerationHistoryResponse(**result)


@router.get(
    "/generation/{generation_id}",
    response_model=GenerationDetailResponse,
    summary="Get generation details",
    description=(
        "Returns a single generation with its test cases and a live "
        "staleness check against the current document state."
    ),
    response_description="Generation details with staleness information.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_GENERATION,
    },
)
async def retrieve_generation(
    generation_id: str,
    db: Session = Depends(get_db),
) -> GenerationDetailResponse:
    """Retrieve a single generation with staleness information.

    Args:
        generation_id: UUID of the generation.

    Returns:
        ``GenerationDetailResponse`` with test cases and staleness.

    Raises:
        422: If ``generation_id`` is not a valid UUID.
        404: If the generation does not exist.
    """
    validate_uuid(generation_id, "generation_id")

    doc = get_generation_with_staleness(db, generation_id)
    if doc is None:
        raise not_found_error(
            "Generation",
            generation_id,
            "Check the generation ID or create a new generation with POST /generate.",
        )
    return GenerationDetailResponse(**doc)


@router.get(
    "/node/{node_id}/generations",
    response_model=GenerationHistoryResponse,
    summary="List generations for a node",
    description=(
        "Returns all generations that included a specific node in their "
        "selection. Useful for tracking how a node's test coverage has "
        "evolved over time."
    ),
    response_description="Paginated generation list.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
    },
)
async def node_generations(
    node_id: str,
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of results (1-100)",
        examples=[20],
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset",
        examples=[0],
    ),
) -> GenerationHistoryResponse:
    """Return all generations that included a specific node.

    Args:
        node_id: UUID of the node.
        limit: Maximum results per page.
        offset: Pagination offset.

    Returns:
        ``GenerationHistoryResponse`` with matching generations.

    Raises:
        422: If ``node_id`` is not a valid UUID.
    """
    validate_uuid(node_id, "node_id")

    result = get_generations_for_node(
        node_id=node_id,
        limit=limit,
        offset=offset,
    )
    return GenerationHistoryResponse(**result)


@router.get(
    "/selection/{selection_id}/generations",
    response_model=GenerationHistoryResponse,
    summary="List generations for a selection",
    description=(
        "Returns all generations produced from a specific selection, "
        "ordered by generation date descending."
    ),
    response_description="Paginated generation list.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
    },
)
async def selection_generations(
    selection_id: str,
    limit: int = Query(
        20,
        ge=1,
        le=100,
        description="Maximum number of results (1-100)",
        examples=[20],
    ),
    offset: int = Query(
        0,
        ge=0,
        description="Pagination offset",
        examples=[0],
    ),
) -> GenerationHistoryResponse:
    """Return all generations for a specific selection.

    Args:
        selection_id: UUID of the selection.
        limit: Maximum results per page.
        offset: Pagination offset.

    Returns:
        ``GenerationHistoryResponse`` with matching generations.

    Raises:
        422: If ``selection_id`` is not a valid UUID.
    """
    validate_uuid(selection_id, "selection_id")

    result = get_generations_for_selection(
        selection_id=selection_id,
        limit=limit,
        offset=offset,
    )
    return GenerationHistoryResponse(**result)
