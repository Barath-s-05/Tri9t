"""Selections management API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.schemas.api import (
    ERROR_RESPONSE_INVALID_UUID,
    ErrorResponse,
    not_found_error,
    validation_error,
    validate_uuid,
)
from tri9t.app.services.selection_service import (
    create_selection,
    delete_selection,
    get_selection,
    get_selections,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/selections", tags=["selections"])

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateSelectionRequest(BaseModel):
    """Request body for creating a selection."""

    selection_name: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Unique name for this selection within the document version",
        examples=["Critical Safety Checks"],
    )
    description: str | None = Field(
        None,
        max_length=2048,
        description="Optional human-readable description",
        examples=["All nodes related to emergency shutdown procedures"],
    )
    document_version_id: str = Field(
        ...,
        description="UUID of the document version to pin nodes to",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    node_ids: list[str] = Field(
        ...,
        min_length=1,
        description="Ordered list of node UUIDs to include (must all belong to the same version)",
        examples=[["node-uuid-1", "node-uuid-2"]],
    )
    created_by: str | None = Field(
        None,
        max_length=128,
        description="Optional creator identifier",
        examples=["qa-engineer-1"],
    )


class SelectionResponse(BaseModel):
    """Response for a single selection."""

    id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    selection_name: str = Field(..., examples=["Critical Safety Checks"])
    document_version_id: str = Field(..., examples=["550e8400-..."])
    node_ids: list[str] = Field(..., examples=[["node-1", "node-2"]])
    created_by: str | None = Field(None, examples=["qa-engineer-1"])
    created_at: str | None = Field(None)


class SelectionListResponse(BaseModel):
    """Response for listing selections."""

    selections: list[SelectionResponse] = Field(
        ...,
        description="List of selections ordered by creation date descending",
    )


class DeleteSelectionResponse(BaseModel):
    """Response for successful deletion."""

    message: str = Field(
        ...,
        description="Confirmation message",
        examples=["Selection deleted successfully."],
    )


# ---------------------------------------------------------------------------
# OpenAPI response configs
# ---------------------------------------------------------------------------

_DOCS_404_SELECTION: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Selection not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "SelectionNotFound",
                    "message": "Selection '550e8400-...' was not found.",
                    "hint": "Use GET /selections to list available selections.",
                }
            }
        },
    },
}

_DOCS_422_CREATE: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Validation error (duplicate name, invalid nodes, etc.)",
        "content": {
            "application/json": {
                "example": {
                    "error": "DuplicateSelectionName",
                    "message": "Selection 'My Selection' already exists for this version.",
                    "hint": "Choose a different name or update the existing selection.",
                }
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/",
    response_model=SelectionResponse,
    summary="Create a selection",
    description=(
        "Create a new named, version-pinned selection of document nodes. "
        "All node IDs must belong to the same document version."
    ),
    response_description="The newly created selection with its ID.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_422_CREATE,
    },
)
def create_selection_api(
    body: CreateSelectionRequest,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    """Create a new version-pinned selection.

    Args:
        body: Selection creation payload with name, version ID, and node IDs.

    Returns:
        ``SelectionResponse`` with the new selection's details.

    Raises:
        422: If validation fails (duplicate name, invalid nodes, mixed versions).
    """
    validate_uuid(body.document_version_id, "document_version_id")
    for i, nid in enumerate(body.node_ids):
        validate_uuid(nid, f"node_ids[{i}]")

    try:
        selection = create_selection(
            db,
            selection_name=body.selection_name,
            description=body.description,
            document_version_id=body.document_version_id,
            node_ids=body.node_ids,
            created_by=body.created_by,
        )
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise validation_error(
                "DuplicateSelectionName",
                msg,
                "Choose a different name or update the existing selection.",
            ) from exc
        if "empty" in msg:
            raise validation_error(
                "EmptyNodeList",
                msg,
                "Provide at least one node ID.",
            ) from exc
        if "not found" in msg.lower():
            raise validation_error(
                "InvalidNodeIds",
                msg,
                "Verify all node IDs exist in the database.",
            ) from exc
        if "different version" in msg:
            raise validation_error(
                "MixedVersionNodes",
                msg,
                "Ensure all nodes belong to the same document version.",
            ) from exc
        raise validation_error("SelectionError", msg) from exc

    logger.info(
        "Created selection '%s' for version %s (%d nodes)",
        body.selection_name,
        body.document_version_id,
        len(body.node_ids),
    )

    return SelectionResponse(
        id=selection.id,
        selection_name=selection.selection_name,
        document_version_id=selection.document_version_id,
        node_ids=selection.node_ids,
        created_by=selection.created_by,
        created_at=(
            selection.created_at.isoformat()
            if selection.created_at
            else datetime.now(timezone.utc).isoformat()
        ),
    )


@router.get(
    "/",
    response_model=SelectionListResponse,
    summary="List selections",
    description=(
        "Returns all selections, optionally filtered by document version. "
        "Selections are ordered by creation date descending."
    ),
    response_description="List of selections.",
)
def list_selections(
    document_version_id: str | None = Query(
        None,
        description="Optional UUID to filter selections by document version",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    db: Session = Depends(get_db),
) -> SelectionListResponse:
    """List selections, optionally filtered by document version.

    Args:
        document_version_id: Optional version UUID to filter.

    Returns:
        ``SelectionListResponse`` with matching selections.
    """
    if document_version_id is not None:
        validate_uuid(document_version_id, "document_version_id")

    selections = get_selections(db, document_version_id=document_version_id)
    return SelectionListResponse(selections=selections)


@router.get(
    "/{selection_id}",
    response_model=SelectionResponse,
    summary="Get selection by ID",
    description="Returns a single selection identified by its UUID.",
    response_description="Selection details.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_SELECTION,
    },
)
def get_selection_api(
    selection_id: str,
    db: Session = Depends(get_db),
) -> SelectionResponse:
    """Get a selection by ID.

    Args:
        selection_id: UUID of the selection.

    Returns:
        ``SelectionResponse`` with selection details.

    Raises:
        422: If ``selection_id`` is not a valid UUID.
        404: If the selection does not exist.
    """
    validate_uuid(selection_id, "selection_id")

    selection = get_selection(db, selection_id)
    if selection is None:
        raise not_found_error(
            "Selection",
            selection_id,
            "Use GET /selections to list available selections.",
        )
    return SelectionResponse(**selection)


@router.delete(
    "/{selection_id}",
    response_model=DeleteSelectionResponse,
    summary="Delete a selection",
    description="Permanently deletes a selection by its UUID.",
    response_description="Confirmation message.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_SELECTION,
    },
)
def delete_selection_api(
    selection_id: str,
    db: Session = Depends(get_db),
) -> DeleteSelectionResponse:
    """Delete a selection by ID.

    Args:
        selection_id: UUID of the selection.

    Returns:
        ``DeleteSelectionResponse`` confirming deletion.

    Raises:
        422: If ``selection_id`` is not a valid UUID.
        404: If the selection does not exist.
    """
    validate_uuid(selection_id, "selection_id")

    if not delete_selection(db, selection_id):
        raise not_found_error(
            "Selection",
            selection_id,
            "Use GET /selections to list available selections.",
        )

    logger.info("Deleted selection %s", selection_id)
    return DeleteSelectionResponse(message="Selection deleted successfully.")
