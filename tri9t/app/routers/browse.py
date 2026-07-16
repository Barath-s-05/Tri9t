"""Document browsing API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.schemas.api import (
    ERROR_RESPONSE_INVALID_UUID,
    ERROR_RESPONSE_NOT_FOUND,
    ErrorResponse,
    PaginationMeta,
    not_found_error,
    validate_uuid,
)
from tri9t.app.services.browse_service import (
    get_document,
    get_node,
    get_node_children,
    get_tree,
    list_documents,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browse"])

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DocumentSummary(BaseModel):
    """Summary of a document for list views."""

    id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    filename: str = Field(..., examples=["spec_v2.pdf"])
    title: str | None = Field(None, examples=["System Specification"])
    version_count: int = Field(..., examples=[3])
    created_at: str | None = Field(None)


class DocumentListResponse(BaseModel):
    """Response for listing all documents."""

    documents: list[DocumentSummary] = Field(
        ...,
        description="List of document summaries, ordered by creation date descending",
    )
    page: int = Field(..., description="Current page number", examples=[1])
    limit: int = Field(..., description="Items per page", examples=[20])
    total: int = Field(..., description="Total number of documents", examples=[42])
    pages: int = Field(..., description="Total number of pages", examples=[3])


class DocumentDetailResponse(BaseModel):
    """Response for a single document with its versions."""

    document: dict = Field(
        ...,
        description="Document details including version history",
    )


class TreeData(BaseModel):
    """Hierarchical tree for a document version."""

    version_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    version_number: int = Field(..., examples=[2])
    document_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    tree: list[dict] = Field(
        ...,
        description="Root nodes with nested children forming the hierarchy",
    )


class TreeResponse(BaseModel):
    """Response for tree endpoints."""

    tree: TreeData = Field(..., description="Hierarchical tree data")


class NodeDetailResponse(BaseModel):
    """Response for a single node with children."""

    node: dict = Field(
        ...,
        description="Node details including children array",
    )


class NodeChildrenResponse(BaseModel):
    """Response for node children endpoint."""

    node_id: str = Field(..., examples=["550e8400-e29b-41d4-a716-446655440000"])
    children: list[dict] = Field(
        ...,
        description="Direct child nodes",
    )


# ---------------------------------------------------------------------------
# OpenAPI response configs
# ---------------------------------------------------------------------------

_DOCS_404_DOC: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Document not found",
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

_DOCS_404_NODE: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Node not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "NodeNotFound",
                    "message": "Node '550e8400-...' was not found.",
                    "hint": "Use GET /documents/{id}/tree to browse available nodes.",
                }
            }
        },
    },
}

_DOCS_404_VERSION: dict[int, dict] = {
    404: {
        "model": ErrorResponse,
        "description": "Version not found",
        "content": {
            "application/json": {
                "example": {
                    "error": "VersionNotFound",
                    "message": "Version '550e8400-...' was not found.",
                    "hint": "Use GET /versions/document/{id}/versions to list version IDs.",
                }
            }
        },
    },
}

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List all documents",
    description=(
        "Returns a paginated list of all uploaded documents. "
        "Supports sorting by ``sort`` param and filtering by ``title``."
    ),
    response_description="Paginated list of document summaries.",
)
def browse_documents(
    page: int = Query(1, ge=1, description="Page number (1-based)", examples=[1]),
    limit: int = Query(20, ge=1, le=100, description="Items per page (1-100)", examples=[20]),
    sort: str | None = Query(
        None,
        description="Field to sort by (created_at, title, filename)",
        examples=["created_at"],
    ),
    order: str = Query("desc", description="Sort order: asc or desc", examples=["desc"]),
    title: str | None = Query(None, description="Filter by document title (substring match)", examples=["CT200"]),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    """List all documents with pagination, sorting, and filtering.

    Returns:
        ``DocumentListResponse`` containing paginated documents.
    """
    from tri9t.app.services.browse_service import list_documents

    docs = list_documents(db, sort=sort, order=order, title=title)

    total = len(docs)
    pages = max(1, (total + limit - 1) // limit)
    start = (page - 1) * limit
    page_docs = docs[start : start + limit]

    logger.debug("Listed %d documents (page %d/%d)", len(page_docs), page, pages)
    return DocumentListResponse(
        documents=page_docs,
        page=page,
        limit=limit,
        total=total,
        pages=pages,
    )


@router.get(
    "/documents/{document_id}",
    response_model=DocumentDetailResponse,
    summary="Get document details",
    description=(
        "Returns full details for a single document, including its "
        "filename, title, and version history."
    ),
    response_description="Document details with version list.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_DOC,
    },
)
def browse_document(
    document_id: str,
    db: Session = Depends(get_db),
) -> DocumentDetailResponse:
    """Get a single document with its versions.

    Args:
        document_id: UUID of the document.

    Returns:
        ``DocumentDetailResponse`` with document metadata and versions.

    Raises:
        422: If ``document_id`` is not a valid UUID.
        404: If the document does not exist.
    """
    validate_uuid(document_id, "document_id")

    doc = get_document(db, document_id)
    if doc is None:
        raise not_found_error(
            "Document",
            document_id,
            "Use GET /documents to list available documents.",
        )
    return DocumentDetailResponse(document=doc)


@router.get(
    "/documents/{document_id}/tree",
    response_model=TreeResponse,
    summary="Get document tree",
    description=(
        "Returns the hierarchical tree for the latest version of a "
        "document. Nodes are nested according to their parent-child "
        "relationships."
    ),
    response_description="Hierarchical tree of the latest version.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_DOC,
    },
)
def browse_document_tree(
    document_id: str,
    db: Session = Depends(get_db),
) -> TreeResponse:
    """Get the latest version tree for a document.

    Args:
        document_id: UUID of the document.

    Returns:
        ``TreeResponse`` with the hierarchical tree.

    Raises:
        422: If ``document_id`` is not a valid UUID.
        404: If the document or its tree does not exist.
    """
    validate_uuid(document_id, "document_id")

    from tri9t.app.models.document import DocumentVersion

    version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.is_latest == True,  # noqa: E712
        )
        .first()
    )
    if version is None:
        raise not_found_error(
            "Document",
            document_id,
            "Upload a document first with POST /ingest/document.",
        )

    result = get_tree(db, version.id)
    if result is None:
        raise not_found_error(
            "Tree",
            document_id,
            "The latest version has no tree data.",
        )
    return TreeResponse(tree=result)


@router.get(
    "/nodes/{node_id}",
    response_model=NodeDetailResponse,
    summary="Get node details",
    description=(
        "Returns a single node with its direct children. The node is "
        "identified by its unique ID."
    ),
    response_description="Node details with children array.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_NODE,
    },
)
def browse_node(
    node_id: str,
    db: Session = Depends(get_db),
) -> NodeDetailResponse:
    """Get a single node with its children.

    Args:
        node_id: UUID of the node.

    Returns:
        ``NodeDetailResponse`` with node data and children.

    Raises:
        422: If ``node_id`` is not a valid UUID.
        404: If the node does not exist.
    """
    validate_uuid(node_id, "node_id")

    node = get_node(db, node_id)
    if node is None:
        raise not_found_error(
            "Node",
            node_id,
            "Use GET /documents/{id}/tree to browse available nodes.",
        )
    return NodeDetailResponse(node=node)


@router.get(
    "/nodes/{node_id}/children",
    response_model=NodeChildrenResponse,
    summary="Get node children",
    description=(
        "Returns the direct children of a node. Use this to traverse "
        "the tree level by level."
    ),
    response_description="List of direct child nodes.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
    },
)
def browse_node_children(
    node_id: str,
    db: Session = Depends(get_db),
) -> NodeChildrenResponse:
    """Get the direct children of a node.

    Args:
        node_id: UUID of the parent node.

    Returns:
        ``NodeChildrenResponse`` with the child nodes.

    Raises:
        422: If ``node_id`` is not a valid UUID.
    """
    validate_uuid(node_id, "node_id")

    children = get_node_children(db, node_id)
    return NodeChildrenResponse(node_id=node_id, children=children)


@router.get(
    "/versions/{version_id}/tree",
    response_model=TreeResponse,
    summary="Get tree for a specific version",
    description=(
        "Returns the hierarchical tree for a specific document version. "
        "Unlike the ``/documents/{id}/tree`` endpoint, this allows you "
        "to inspect older versions."
    ),
    response_description="Hierarchical tree for the specified version.",
    responses={
        **ERROR_RESPONSE_INVALID_UUID,
        **_DOCS_404_VERSION,
    },
)
def browse_version_tree(
    version_id: str,
    db: Session = Depends(get_db),
) -> TreeResponse:
    """Get the hierarchical tree for a specific document version.

    Args:
        version_id: UUID of the document version.

    Returns:
        ``TreeResponse`` with the hierarchical tree.

    Raises:
        422: If ``version_id`` is not a valid UUID.
        404: If the version does not exist.
    """
    validate_uuid(version_id, "version_id")

    result = get_tree(db, version_id)
    if result is None:
        raise not_found_error(
            "Version",
            version_id,
            "Use GET /versions/document/{id}/versions to list version IDs.",
        )
    return TreeResponse(tree=result)
