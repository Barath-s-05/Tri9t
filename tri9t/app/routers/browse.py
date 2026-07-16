"""Document browsing API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tri9t.app.db.database import get_db
from tri9t.app.services.browse_service import (
    get_document,
    get_node,
    get_node_children,
    get_tree,
    list_documents,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browse"])


class DocumentListResponse(BaseModel):
    documents: list[dict]


class DocumentResponse(BaseModel):
    document: dict


class TreeResponse(BaseModel):
    tree: dict


class NodeResponse(BaseModel):
    node: dict


@router.get("/documents", response_model=DocumentListResponse)
def browse_documents(db: Session = Depends(get_db)) -> DocumentListResponse:
    """List all documents with version counts."""
    return DocumentListResponse(documents=list_documents(db))


@router.get("/documents/{document_id}", response_model=DocumentResponse)
def browse_document(
    document_id: str,
    db: Session = Depends(get_db),
) -> DocumentResponse:
    """Get a single document with its versions."""
    doc = get_document(db, document_id)
    if doc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentResponse(document=doc)


@router.get("/documents/{document_id}/tree", response_model=TreeResponse)
def browse_document_tree(
    document_id: str,
    db: Session = Depends(get_db),
) -> TreeResponse:
    """Get the latest version tree for a document."""
    from tri9t.app.models.document import DocumentVersion

    version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.is_latest == True,
        )
        .first()
    )
    if version is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No version found for document")
    result = get_tree(db, version.id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Tree not found")
    return TreeResponse(tree=result)


@router.get("/nodes/{node_id}", response_model=NodeResponse)
def browse_node(
    node_id: str,
    db: Session = Depends(get_db),
) -> NodeResponse:
    """Get a single node with its children."""
    node = get_node(db, node_id)
    if node is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Node not found")
    return NodeResponse(node=node)


@router.get("/nodes/{node_id}/children")
def browse_node_children(
    node_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """Get the direct children of a node."""
    children = get_node_children(db, node_id)
    return {"node_id": node_id, "children": children}


@router.get("/versions/{version_id}/tree", response_model=TreeResponse)
def browse_version_tree(
    version_id: str,
    db: Session = Depends(get_db),
) -> TreeResponse:
    """Get the hierarchical tree for a specific document version."""
    result = get_tree(db, version_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Version not found")
    return TreeResponse(tree=result)
