"""QA generation API endpoints.

Thin layer that parses requests and delegates to
``generation_service``.  No business logic lives here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.generation_service import (
    GenerationError,
    generate_test_cases,
    get_generation,
    get_generation_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generation"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class GenerateRequest(BaseModel):
    """Body for ``POST /generate``."""

    selection_id: str
    model: str | None = None
    temperature: float | None = None


class GenerateResponse(BaseModel):
    """Successful generation response."""

    generation_id: str
    test_cases: list[dict]
    metadata: dict


class GenerationHistoryResponse(BaseModel):
    """Paginated history response."""

    generations: list[dict]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate", response_model=GenerateResponse)
async def generate(
    body: GenerateRequest,
    db: Session = Depends(get_db),
) -> GenerateResponse:
    """Trigger QA test-case generation from a selection."""
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
            raise HTTPException(status_code=404, detail=str(exc))
        if "no nodes" in msg or "no valid nodes" in msg:
            raise HTTPException(status_code=422, detail=str(exc))
        if "no groq api key" in msg:
            raise HTTPException(status_code=503, detail=str(exc))
        raise HTTPException(status_code=500, detail=str(exc))


@router.get(
    "/generation/history",
    response_model=GenerationHistoryResponse,
)
async def history(
    selection_id: str | None = Query(None),
    version_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> GenerationHistoryResponse:
    """Return paginated generation history."""
    result = get_generation_history(
        selection_id=selection_id,
        version_id=version_id,
        limit=limit,
        offset=offset,
    )
    return GenerationHistoryResponse(**result)


@router.get("/generation/{generation_id}")
async def retrieve_generation(generation_id: str) -> dict:
    """Retrieve a single generation by its ID."""
    doc = get_generation(generation_id)
    if doc is None:
        raise HTTPException(
            status_code=404, detail="Generation not found"
        )
    return doc
