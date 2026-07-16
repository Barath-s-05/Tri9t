"""Selection management service.

Handles creation, retrieval, and deletion of named, version-pinned
node selections.  Validates node existence, prevents duplicate names
for the same version, and rejects mixed-version selections.
"""

from __future__ import annotations

import hashlib
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from tri9t.app.models.node import Node
from tri9t.app.models.selection import Selection

logger = logging.getLogger(__name__)


def _compute_snapshot_hash(node_ids: list[str]) -> str:
    """Compute a deterministic hash for a set of node IDs.

    Args:
        node_ids: Ordered list of node IDs.

    Returns:
        SHA-256 hex string.
    """
    raw = ",".join(sorted(node_ids))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_selection(
    db: Session,
    selection_name: str,
    description: str | None,
    document_version_id: str,
    node_ids: list[str],
    created_by: str | None,
) -> Selection:
    """Create a new selection.

    Validates:
    - No duplicate name for the same document version.
    - All node IDs exist.
    - All nodes belong to the specified version.

    Args:
        db: Active SQLAlchemy session.
        selection_name: Name of the selection.
        description: Optional description.
        document_version_id: ID of the document version to pin.
        node_ids: List of node IDs to include.
        created_by: Optional creator identifier.

    Returns:
        The newly persisted Selection.

    Raises:
        ValueError: If validation fails.
    """
    # Validate duplicate name
    existing = (
        db.query(Selection)
        .filter(
            Selection.selection_name == selection_name,
            Selection.document_version_id == document_version_id,
        )
        .first()
    )
    if existing is not None:
        raise ValueError(
            f"Selection '{selection_name}' already exists for this version"
        )

    if not node_ids:
        raise ValueError("Cannot create selection with empty node list")

    # Validate node IDs exist and all belong to the specified version
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    if len(nodes) != len(node_ids):
        existing_ids = {n.id for n in nodes}
        missing = [str(xid) for xid in node_ids if xid not in existing_ids]
        raise ValueError(f"Node(s) not found: {missing}")

    for node in nodes:
        if node.version_id != document_version_id:
            raise ValueError(
                f"Node {node.id} belongs to a different version "
                f"({node.version_id} != {document_version_id})"
            )

    snapshot_hash = _compute_snapshot_hash(node_ids)

    selection = Selection(
        id=str(uuid4()),
        selection_name=selection_name,
        description=description or "",
        document_version_id=document_version_id,
        snapshot_hash=snapshot_hash,
        created_by=created_by,
        node_ids=node_ids,
    )
    db.add(selection)
    db.commit()
    db.refresh(selection)

    logger.info(
        "Created selection '%s' for version %s (%d nodes)",
        selection_name,
        document_version_id,
        len(node_ids),
    )
    return selection


def get_selections(
    db: Session,
    document_version_id: str | None = None,
) -> list[dict]:
    """Retrieve all selections, optionally filtered by version.

    Args:
        db: Active SQLAlchemy session.
        document_version_id: Optional version ID to filter.

    Returns:
        List of selection dicts.
    """
    q = db.query(Selection)
    if document_version_id:
        q = q.filter(Selection.document_version_id == document_version_id)
    selections = q.order_by(Selection.created_at.desc()).all()

    return [
        {
            "id": s.id,
            "selection_name": s.selection_name,
            "description": s.description or "",
            "document_version_id": s.document_version_id,
            "snapshot_hash": s.snapshot_hash,
            "created_by": s.created_by,
            "node_ids": s.node_ids,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in selections
    ]


def get_selection(db: Session, selection_id: str) -> dict | None:
    """Retrieve a single selection by ID.

    Args:
        db: Active SQLAlchemy session.
        selection_id: The selection ID.

    Returns:
        Selection dict or None.
    """
    s = db.query(Selection).filter(Selection.id == selection_id).first()
    if s is None:
        return None

    return {
        "id": s.id,
        "selection_name": s.selection_name,
        "description": s.description or "",
        "document_version_id": s.document_version_id,
        "snapshot_hash": s.snapshot_hash,
        "created_by": s.created_by,
        "node_ids": s.node_ids,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


def delete_selection(db: Session, selection_id: str) -> bool:
    """Delete a selection by ID.

    Args:
        db: Active SQLAlchemy session.
        selection_id: The selection ID.

    Returns:
        True if deletion happened, False if not found.
    """
    s = db.query(Selection).filter(Selection.id == selection_id).first()
    if s is None:
        return False
    db.delete(s)
    db.commit()
    logger.info("Deleted selection %s", selection_id)
    return True
