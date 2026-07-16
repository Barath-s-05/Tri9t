"""Document browsing service.

Provides read-only access to documents, versions, and hierarchical
trees.  All responses preserve the parent-child hierarchy.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node

logger = logging.getLogger(__name__)


def _node_to_dict(node: Node, children: list[dict] | None = None) -> dict:
    """Convert an ORM Node into a serialisable dict.

    Args:
        node: SQLAlchemy Node instance.
        children: Optional nested child dicts.

    Returns:
        Dictionary with all node fields.
    """
    return {
        "id": node.id,
        "heading": node.heading,
        "level": node.level,
        "section_number": node.section_number,
        "body_text": node.body_text or "",
        "logical_node_id": node.logical_node_id,
        "version": node.version_id,
        "parent": node.parent_id,
        "content_hash": node.content_hash,
        "page_number": node.page_number,
        "change_status": node.change_status,
        "impact_level": node.impact_level,
        "node_type": node.node_type,
        "children": children or [],
    }


def list_documents(
    db: Session,
    sort: str | None = None,
    order: str = "desc",
    title: str | None = None,
) -> list[dict]:
    """Return all documents with version counts.

    Args:
        db: Active SQLAlchemy session.
        sort: Optional field to sort by (created_at, title, filename).
        order: Sort direction — ``asc`` or ``desc`` (default ``desc``).
        title: Optional substring filter on document title.

    Returns:
        List of document summary dicts.
    """
    q = db.query(Document)

    if title:
        q = q.filter(Document.title.ilike(f"%{title}%"))

    # Sorting
    sort_col = Document.created_at  # default
    if sort == "title":
        sort_col = Document.title
    elif sort == "filename":
        sort_col = Document.filename
    elif sort == "created_at":
        sort_col = Document.created_at

    if order.lower() == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    documents = q.all()
    results: list[dict] = []
    for doc in documents:
        version_count = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.document_id == doc.id)
            .count()
        )
        results.append({
            "id": doc.id,
            "filename": doc.filename,
            "title": doc.title,
            "version_count": version_count,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        })
    return results


def get_document(db: Session, document_id: str) -> dict | None:
    """Retrieve a single document with its versions.

    Args:
        db: Active SQLAlchemy session.
        document_id: The document to look up.

    Returns:
        Document dict with versions list, or None.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        return None

    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number)
        .all()
    )

    return {
        "id": doc.id,
        "filename": doc.filename,
        "title": doc.title,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "versions": [
            {
                "version_id": v.id,
                "version_number": v.version_number,
                "label": v.label,
                "is_latest": v.is_latest,
                "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
            }
            for v in versions
        ],
    }


def get_tree(db: Session, version_id: str) -> dict | None:
    """Build a hierarchical tree for a specific document version.

    Args:
        db: Active SQLAlchemy session.
        version_id: The document version to build the tree for.

    Returns:
        Dict with a ``tree`` key containing the root nodes with nested
        children, or None if version not found.
    """
    version = (
        db.query(DocumentVersion).filter(DocumentVersion.id == version_id).first()
    )
    if version is None:
        return None

    nodes = (
        db.query(Node)
        .filter(Node.version_id == version_id)
        .order_by(Node.level, Node.section_number)
        .all()
    )

    node_map: dict[str, dict] = {}
    roots: list[dict] = []

    for node in nodes:
        node_dict = _node_to_dict(node)
        node_map[node.id] = node_dict

    for node in nodes:
        entry = node_map[node.id]
        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id]["children"].append(entry)
        else:
            roots.append(entry)

    return {
        "version_id": version_id,
        "version_number": version.version_number,
        "document_id": version.document_id,
        "tree": roots,
    }


def get_node(db: Session, node_id: str) -> dict | None:
    """Retrieve a single node with its children.

    Args:
        db: Active SQLAlchemy session.
        node_id: The node to look up.

    Returns:
        Node dict with children list, or None.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        return None

    children = (
        db.query(Node)
        .filter(Node.parent_id == node_id)
        .order_by(Node.level, Node.section_number)
        .all()
    )

    return _node_to_dict(node, children=[_node_to_dict(c) for c in children])


def get_node_children(db: Session, node_id: str) -> list[dict]:
    """Retrieve the direct children of a node.

    Args:
        db: Active SQLAlchemy session.
        node_id: The parent node.

    Returns:
        List of child node dicts.
    """
    children = (
        db.query(Node)
        .filter(Node.parent_id == node_id)
        .order_by(Node.level, Node.section_number)
        .all()
    )
    return [_node_to_dict(c) for c in children]
