"""Document ingestion router — PDF upload and parse pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.document_loader import save_document
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.pdf_parser import identify_nodes, parse_pdf
from tri9t.app.services.parser_report import Timer, build_report
from tri9t.app.services.parser_validator import validate_tree
from tri9t.app.services.tree_builder import build_tree

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestResponse(BaseModel):
    """Response model for document ingestion."""

    document_id: str
    node_count: int
    parser_report: dict


@router.post("/document", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> IngestResponse:
    """Upload a PDF, parse it into a hierarchical tree, and store it.

    Pipeline:
        Receive PDF → Extract text → Detect headings → Build hierarchy →
        Generate hashes → Validate → Store in DB → Return report

    Args:
        file: Uploaded PDF file (multipart/form-data).
        db: Database session dependency.

    Returns:
        IngestResponse with document_id, node_count, and parser_report.
    """
    pdf_bytes = await file.read()

    with Timer() as timer:
        # Step 1: Extract text blocks from PDF
        blocks, pages_processed, extraction_warnings = parse_pdf(pdf_bytes)

        # Step 2: Identify headings and create nodes
        nodes, identification_warnings = identify_nodes(blocks, pages_processed)

        # Step 3: Build hierarchical tree
        tree_nodes, tree_warnings = build_tree(nodes)

        # Step 4: Generate content hashes
        for node in tree_nodes:
            node.content_hash = compute_content_hash(node.heading, node.body_text)

        # Step 5: Validate tree structure
        validation_warnings = validate_tree(tree_nodes)

        # Step 6: Aggregate warnings
        all_warnings = (
            extraction_warnings
            + identification_warnings
            + tree_warnings
            + validation_warnings
        )

        # Step 7: Count stats
        headings_detected = sum(
            1 for n in tree_nodes if n.node_type.startswith("section")
        )
        tables_detected = sum(
            1 for n in tree_nodes if "table" in n.node_type
        )
        lists_detected = sum(
            1 for n in tree_nodes if "list" in n.node_type
        )

        # Step 8: Build report
        report = build_report(
            pages_processed=pages_processed,
            nodes_created=len(tree_nodes),
            headings_detected=headings_detected,
            tables_detected=tables_detected,
            lists_detected=lists_detected,
            warnings=all_warnings,
            processing_time_ms=timer.elapsed_ms,
        )

        # Step 9: Persist to database
        document_id, node_count = save_document(
            db=db,
            filename=file.filename or "unknown.pdf",
            nodes=tree_nodes,
            report=report,
        )

    logger.info(
        "Ingested '%s' → %s (%d nodes, %.1f ms)",
        file.filename,
        document_id,
        node_count,
        report.processing_time_ms,
    )

    return IngestResponse(
        document_id=document_id,
        node_count=node_count,
        parser_report=report.to_dict(),
    )
