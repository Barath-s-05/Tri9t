"""Document versioning API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
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
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.pdf_parser import identify_nodes, parse_pdf
from tri9t.app.services.parser_report import Timer, build_report
from tri9t.app.services.tree_builder import build_tree
from tri9t.app.services.versioning_service import (
    create_new_version,
    get_node_changes,
    get_version_history,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/versions", tags=["versions"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class VersionIngestResponse(BaseModel):
    """Response for POST /versions/ingest."""

    document_id: str = Field(
        ...,
        description="ID of the parent document",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    version_id: str = Field(
        ...,
        description="UUID of the newly created version",
        examples=["660e8400-e29b-41d4-a716-446655440001"],
    )
    version_number: int = Field(
        ...,
        description="Sequential version number (1, 2, 3, ...)",
        examples=[2],
    )
    node_count: int = Field(
        ...,
        description="Number of nodes in the new version",
        examples=[45],
    )
    matched_count: int = Field(
        ...,
        description="Number of nodes matched to the previous version",
        examples=[40],
    )


class VersionSummary(BaseModel):
    """Summary of a single document version."""

    version_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    version_number: int = Field(..., examples=[2])
    label: str | None = Field(None, examples=["v2"])
    is_latest: bool = Field(..., examples=[True])
    uploaded_at: str | None = Field(None)


class VersionHistoryResponse(BaseModel):
    """Response for version history endpoint."""

    document_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    versions: list[VersionSummary] = Field(
        ...,
        description="All versions ordered by version number",
    )


class FieldChange(BaseModel):
    """A single field change between versions."""

    field_name: str = Field(..., examples=["body_text"])
    old_value: str = Field(..., examples=["Battery threshold: 15%"])
    new_value: str = Field(..., examples=["Battery threshold: 10%"])


class NodeChangesResponse(BaseModel):
    """Response for node change history endpoint."""

    node_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    logical_node_id: str = Field(..., examples=["aaa-bbb-ccc"])
    heading: str = Field(..., examples=["1.2 Battery"])
    old_hash: str | None = Field(None, examples=["abc123..."])
    new_hash: str = Field(..., examples=["def456..."])
    change_type: str = Field(
        ...,
        description="One of: 'added', 'modified', 'unchanged', 'removed'",
        examples=["modified"],
    )
    changed_fields: list[FieldChange] | None = Field(
        None,
        description="List of fields that changed between versions",
    )
    summaries: list[str] = Field(
        ...,
        description="Human-readable change summaries",
        examples=[["Body text: 15% → 10%"]],
    )
    impact_level: str | None = Field(
        None,
        description="Impact classification: LOW, MEDIUM, HIGH, or CRITICAL",
        examples=["MEDIUM"],
    )


# ---------------------------------------------------------------------------
# OpenAPI response configs
# ---------------------------------------------------------------------------

_DOCS_404_DOCUMENT: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Document not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "DocumentNotFound",
                    "message": "Document '550e8400-...' was not found.",
                    "hint": "Upload a document first with POST /ingest/document.",
                }
            }
        },
    },
}

_DOCS_404_NODE: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Node not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "NodeNotFound",
                    "message": "Node '550e8400-...' was not found.",
                    "hint": "Ensure the node exists in the database.",
                }
            }
        },
    },
}

_DOCS_422_FILE: dict[int, dict] = {
    422: {
        "model": ErrorResponse,
        "description": "Invalid file upload",
        "content": {
            "application/json": {
                "example": {
                    "error": "InvalidUpload",
                    "message": "Uploaded file is not a valid PDF.",
                    "hint": "Ensure the file is a PDF with extractable text.",
                }
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/ingest",
    response_model=VersionIngestResponse,
    summary="Upload a new document version",
    description=(
        "Upload a newer version of an existing document. The PDF is "
        "parsed, nodes are matched against the previous version using "
        "multi-factor heuristics, and a new versioned snapshot is created."
    ),
    response_description="Version metadata and node matching statistics.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_DOCUMENT,
        **_DOCS_422_FILE,
    },
)
async def ingest_new_version(
    document_id: str = Query(
        ...,
        description="UUID of the existing document to add a version to",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    ),
    file: UploadFile = File(
        ...,
        description="PDF file for the new version (multipart/form-data)",
    ),
    db: Session = Depends(get_db),
) -> VersionIngestResponse:
    """Upload a newer version of an existing document.

    Parses the PDF, matches nodes against the previous version using
    multi-factor heuristics, and creates a new versioned snapshot.

    Args:
        document_id: UUID of the document to add a version to.
        file: Uploaded PDF file.
        db: Database session.

    Returns:
        ``VersionIngestResponse`` with version metadata and match stats.

    Raises:
        422: If ``document_id`` is invalid or the file cannot be parsed.
        404: If the document does not exist.
    """
    validate_uuid(document_id, "document_id")

    filename = file.filename or "unknown.pdf"
    if not filename.lower().endswith(".pdf"):
        raise validation_error(
            "InvalidFileType",
            f"Expected a PDF file but received '{filename}'.",
            "Upload a file with a .pdf extension.",
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise validation_error(
            "EmptyFile",
            "The uploaded file is empty.",
            "Upload a non-empty PDF file.",
        )

    with Timer() as timer:
        blocks, pages, extraction_warnings = parse_pdf(pdf_bytes)
        nodes, identification_warnings = identify_nodes(blocks, pages)
        tree_nodes, tree_warnings = build_tree(nodes)

        for node in tree_nodes:
            node.content_hash = compute_content_hash(node.heading, node.body_text)

        all_warnings = extraction_warnings + identification_warnings + tree_warnings
        report = build_report(
            pages_processed=pages,
            nodes_created=len(tree_nodes),
            headings_detected=sum(
                1 for n in tree_nodes if "section" in n.node_type
            ),
            tables_detected=sum(
                1 for n in tree_nodes if "table" in n.node_type
            ),
            lists_detected=sum(
                1 for n in tree_nodes if "list" in n.node_type
            ),
            warnings=all_warnings,
            processing_time_ms=timer.elapsed_ms,
        )

        try:
            version_info = create_new_version(
                db=db,
                document_id=document_id,
                filename=filename,
                parsed_nodes=tree_nodes,
                report=report,
            )
        except ValueError as exc:
            raise not_found_error(
                "Document",
                document_id,
                "Upload the document first with POST /ingest/document.",
            ) from exc

    matched = sum(1 for m in version_info["matches"] if not m["is_new"])
    logger.info(
        "Created version %d for document %s (%d nodes, %d matched)",
        version_info["version_number"],
        document_id,
        version_info["node_count"],
        matched,
    )

    return VersionIngestResponse(
        document_id=document_id,
        version_id=version_info["version_id"],
        version_number=version_info["version_number"],
        node_count=version_info["node_count"],
        matched_count=matched,
    )


@router.get(
    "/document/{document_id}/versions",
    response_model=VersionHistoryResponse,
    summary="List document versions",
    description=(
        "Returns all versions for a document, ordered by version number. "
        "Each entry includes the version ID, label, and whether it is "
        "the latest."
    ),
    response_description="Ordered list of document versions.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_DOCUMENT,
    },
)
async def list_versions(
    document_id: str,
    db: Session = Depends(get_db),
) -> VersionHistoryResponse:
    """Get version history for a document.

    Args:
        document_id: UUID of the document.

    Returns:
        ``VersionHistoryResponse`` with ordered version list.

    Raises:
        422: If ``document_id`` is not a valid UUID.
    """
    validate_uuid(document_id, "document_id")

    versions = get_version_history(db, document_id)
    return VersionHistoryResponse(
        document_id=document_id,
        versions=versions,
    )


@router.get(
    "/node/{node_id}/changes",
    response_model=NodeChangesResponse,
    summary="Get node change history",
    description=(
        "Compares the two most recent versions that contain the given "
        "logical node. Returns field-level diffs, human-readable "
        "summaries, and an impact classification."
    ),
    response_description="Node change details with field diffs and impact level.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_NODE,
    },
)
async def node_changes(
    node_id: str,
    db: Session = Depends(get_db),
) -> NodeChangesResponse:
    """Get change history for a specific node.

    Resolves the node's logical identity and compares the two most
    recent versions containing that logical node.

    Args:
        node_id: UUID of the node to inspect.

    Returns:
        ``NodeChangesResponse`` with hashes, summaries, and impact level.

    Raises:
        422: If ``node_id`` is not a valid UUID.
        404: If the node does not exist.
    """
    validate_uuid(node_id, "node_id")

    result = get_node_changes(db, node_id)
    if result is None:
        raise not_found_error(
            "Node",
            node_id,
            "Ensure the node exists in the database.",
        )

    return NodeChangesResponse(
        node_id=node_id,
        logical_node_id=result["logical_node_id"],
        heading=result["heading"],
        old_hash=result.get("old_hash"),
        new_hash=result["new_hash"],
        change_type=result["change_type"],
        changed_fields=result.get("changed_fields"),
        summaries=result["summaries"],
        impact_level=result.get("impact_level"),
    )
