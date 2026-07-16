"""Selections management API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.selection_service import (
    create_selection,
    delete_selection,
    get_selection,
    get_selections,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/selections", tags=["selections"])


class CreateSelectionRequest(BaseModel):
    selection_name: str
    description: str | None = None
    document_version_id: str
    node_ids: list[str]
    created_by: str | None = None


class CreateSelectionResponse(BaseModel):
    id: str
    selection_name: str
    document_version_id: str
    node_ids: list[str]
    created_by: str | None
    created_at: str


@router.post("/", response_model=CreateSelectionResponse)
def create_selection_api(
    body: CreateSelectionRequest,
    db: Session = Depends(get_db),
) -> Any:
    """Create a new version-pinned selection."""
    try:
        selection = create_selection(
            db,
            selection_name=body.selection_name,
            description=body.description,
            document_version_id=body.document_version_id,
            node_ids=body.node_ids,
            created_by=body.created_by,
        )
        return CreateSelectionResponse(
            id=selection.id,
            selection_name=selection.selection_name,
            document_version_id=selection.document_version_id,
            node_ids=selection.node_ids,
            created_by=selection.created_by,
            created_at=selection.created_at.isoformat() if selection.created_at else datetime.now(timezone.utc).isoformat(),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/")
def list_selections(
    document_version_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """List selections, optionally filtered by document version."""
    selections = get_selections(db, document_version_id=document_version_id)
    return {"selections": selections}


@router.get("/{selection_id}")
def get_selection_api(
    selection_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Get a selection by ID."""
    selection = get_selection(db, selection_id)
    if selection is None:
        raise HTTPException(status_code=404, detail="Selection not found")
    return selection


@router.delete("/{selection_id}")
def delete_selection_api(
    selection_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Delete a selection by ID."""
    if not delete_selection(db, selection_id):
        raise HTTPException(status_code=404, detail="Selection not found")
    return {"message": "Selection deleted"}
