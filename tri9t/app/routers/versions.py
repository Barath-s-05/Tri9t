"""Document versioning API routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.document_loader import save_document
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


class VersionIngestResponse(BaseModel):
    """Response for POST /versions/ingest."""

    document_id: str
    version_id: str
    version_number: int
    node_count: int
    matched_count: int


class VersionHistoryResponse(BaseModel):
    """Response for GET /document/{id}/versions."""

    document_id: str
    versions: list[dict]


class NodeChangesResponse(BaseModel):
    """Response for GET /node/{id}/changes."""

    node_id: str
    logical_node_id: str
    heading: str
    old_hash: str | None
    new_hash: str
    change_type: str
    changed_fields: list[dict] | None = None
    summaries: list[str]
    impact_level: str | None = None


@router.post("/ingest", response_model=VersionIngestResponse)
async def ingest_new_version(
    document_id: str = Query(..., description="ID of the existing document"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> VersionIngestResponse:
    """Upload a newer version of an existing document.

    Parses the PDF, matches nodes against the previous version using
    multi-factor heuristics, and creates a new versioned snapshot.

    Args:
        document_id: The document to add a version to.
        file: Uploaded PDF file.
        db: Database session.

    Returns:
        VersionIngestResponse with version metadata and match stats.
    """
    pdf_bytes = await file.read()

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
            headings_detected=sum(1 for n in tree_nodes if "section" in n.node_type),
            tables_detected=sum(1 for n in tree_nodes if "table" in n.node_type),
            lists_detected=sum(1 for n in tree_nodes if "list" in n.node_type),
            warnings=all_warnings,
            processing_time_ms=timer.elapsed_ms,
        )

        version_info = create_new_version(
            db=db,
            document_id=document_id,
            filename=file.filename or "unknown.pdf",
            parsed_nodes=tree_nodes,
            report=report,
        )

    return VersionIngestResponse(
        document_id=document_id,
        version_id=version_info["version_id"],
        version_number=version_info["version_number"],
        node_count=version_info["node_count"],
        matched_count=sum(
            1 for m in version_info["matches"] if not m["is_new"]
        ),
    )


@router.get("/document/{document_id}/versions", response_model=VersionHistoryResponse)
async def list_versions(
    document_id: str,
    db: Session = Depends(get_db),
) -> VersionHistoryResponse:
    """Get version history for a document.

    Args:
        document_id: The document to query.
        db: Database session.

    Returns:
        VersionHistoryResponse with ordered version list.
    """
    versions = get_version_history(db, document_id)
    return VersionHistoryResponse(
        document_id=document_id,
        versions=versions,
    )


@router.get("/node/{node_id}/changes", response_model=NodeChangesResponse)
async def node_changes(
    node_id: str,
    db: Session = Depends(get_db),
) -> NodeChangesResponse:
    """Get change history for a specific node.

    Resolves the node's logical identity and compares the two most
    recent versions containing that logical node.

    Args:
        node_id: The node to inspect.
        db: Database session.

    Returns:
        NodeChangesResponse with hashes, summaries, and impact level.
    """
    result = get_node_changes(db, node_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Node not found")

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
