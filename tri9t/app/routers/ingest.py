"""Document ingestion router — PDF upload and parse pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.schemas.api import (
    ErrorResponse,
    validation_error,
)
from tri9t.app.services.document_loader import save_document
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.pdf_parser import identify_nodes, parse_pdf
from tri9t.app.services.parser_report import Timer, build_report
from tri9t.app.services.parser_validator import validate_tree
from tri9t.app.services.tree_builder import build_tree

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class IngestResponse(BaseModel):
    """Response model for document ingestion."""

    document_id: str = Field(
        ...,
        description="Unique identifier of the newly created document",
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )
    node_count: int = Field(
        ...,
        description="Total number of hierarchical nodes extracted",
        examples=[42],
    )
    parser_report: dict = Field(
        ...,
        description="Detailed parser report with pages, headings, warnings, and timing",
    )


class IngestErrorResponse(BaseModel):
    """Error response for ingestion failures."""

    error: str = Field(..., examples=["InvalidUpload"])
    message: str = Field(..., examples=["Uploaded file is not a valid PDF."])
    hint: str | None = Field(
        None,
        examples=["Ensure the file is a PDF with extractable text."],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_ERROR_RESPONSES = {
    422: {
        "model": IngestErrorResponse,
        "description": "Invalid upload or parsing error",
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


@router.post(
    "/document",
    response_model=IngestResponse,
    summary="Upload and parse a PDF document",
    description=(
        "Upload a PDF file to create a new document. The file is parsed "
        "into a hierarchical tree of heading nodes with body text, content "
        "hashes are generated, and the result is stored in the database."
    ),
    response_description="Document ID, node count, and parser report.",
    responses=_ERROR_RESPONSES,
)
async def ingest_document(
    file: UploadFile = File(
        ...,
        description="PDF file to upload (multipart/form-data). "
        "Must have a .pdf extension.",
    ),
    db: Session = Depends(get_db),
) -> IngestResponse:
    """Upload a PDF, parse it into a hierarchical tree, and store it.

    Pipeline::

        Receive PDF -> Extract text -> Detect headings -> Build hierarchy ->
        Generate hashes -> Validate -> Store in DB -> Return report

    Args:
        file: Uploaded PDF file (multipart/form-data).
        db: Database session dependency.

    Returns:
        ``IngestResponse`` with ``document_id``, ``node_count``, and
        ``parser_report``.

    Raises:
        422: If the file cannot be parsed as a PDF.
    """
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
        blocks, pages_processed, extraction_warnings = parse_pdf(pdf_bytes)
        nodes, identification_warnings = identify_nodes(blocks, pages_processed)
        tree_nodes, tree_warnings = build_tree(nodes)

        for node in tree_nodes:
            node.content_hash = compute_content_hash(node.heading, node.body_text)

        validation_warnings = validate_tree(tree_nodes)

        all_warnings = (
            extraction_warnings
            + identification_warnings
            + tree_warnings
            + validation_warnings
        )

        headings_detected = sum(
            1 for n in tree_nodes if n.node_type.startswith("section")
        )
        tables_detected = sum(
            1 for n in tree_nodes if "table" in n.node_type
        )
        lists_detected = sum(
            1 for n in tree_nodes if "list" in n.node_type
        )

        report = build_report(
            pages_processed=pages_processed,
            nodes_created=len(tree_nodes),
            headings_detected=headings_detected,
            tables_detected=tables_detected,
            lists_detected=lists_detected,
            warnings=all_warnings,
            processing_time_ms=timer.elapsed_ms,
        )

        document_id, node_count = save_document(
            db=db,
            filename=filename,
            nodes=tree_nodes,
            report=report,
        )

    logger.info(
        "Ingested '%s' -> %s (%d nodes, %.1f ms)",
        filename,
        document_id,
        node_count,
        report.processing_time_ms,
    )

    return IngestResponse(
        document_id=document_id,
        node_count=node_count,
        parser_report=report.to_dict(),
    )
