"""Document versioning service.

Handles creation of new document versions, logical-node matching
across versions, diff generation, and impact analysis.  This module
orchestrates the lower-level services (node_matcher, diff_engine,
impact_analyzer) and persists results to the database.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.schemas.parser import ParsedNode, ParserReport
from tri9t.app.services.diff_engine import NodeDiff, ChangeType, compute_diff
from tri9t.app.services.impact_analyzer import ImpactLevel, classify_impact
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.node_matcher import match_nodes

logger = logging.getLogger(__name__)


def _node_to_dict(node: Node) -> dict:
    """Convert an ORM Node to a plain dict.

    Args:
        node: SQLAlchemy Node instance.

    Returns:
        Dictionary with node fields.
    """
    return {
        "id": node.id,
        "heading": node.heading,
        "level": node.level,
        "body_text": node.body_text or "",
        "section_number": node.section_number,
        "content_hash": node.content_hash,
        "parent_id": node.parent_id,
        "logical_node_id": node.logical_node_id,
    }


def _parent_heading_map(db: Session, document_id: str) -> dict[str, str]:
    """Build a map of node_id → parent heading text for a document.

    Args:
        db: Active session.
        document_id: The document to query.

    Returns:
        Dict mapping node IDs to their parent's heading text.
    """
    nodes = db.query(Node).filter(Node.document_id == document_id).all()
    node_map = {n.id: n for n in nodes}
    result: dict[str, str] = {}
    for node in nodes:
        if node.parent_id and node.parent_id in node_map:
            result[node.id] = node_map[node.parent_id].heading
    return result


def create_new_version(
    db: Session,
    document_id: str,
    filename: str,
    parsed_nodes: list[ParsedNode],
    report: ParserReport,
) -> dict:
    """Create a new version of an existing document.

    1. Finds the latest version and increments the version number.
    2. Marks the old latest version as ``is_latest = False``.
    3. Matches new nodes against old nodes via multi-factor heuristic.
    4. Assigns ``logical_node_id`` and ``version_id`` to each new node.
    5. Persists the new nodes and returns version metadata.

    Args:
        db: Active session.
        document_id: ID of the existing document.
        filename: Original PDF filename.
        parsed_nodes: Parsed nodes from the new PDF.
        report: Parser report.

    Returns:
        Dict with version_id, version_number, node_count, and matches.
    """
    # Find latest version
    latest = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )
    if latest is None:
        raise ValueError(f"No existing version for document {document_id}")

    new_version_number = latest.version_number + 1
    new_version_id = str(uuid4())

    # Mark old latest as not latest
    latest.is_latest = False
    db.flush()

    new_version = DocumentVersion(
        id=new_version_id,
        document_id=document_id,
        version_number=new_version_number,
        label=f"v{new_version_number}",
        is_latest=True,
    )
    db.add(new_version)
    db.flush()

    # Retrieve old nodes for matching
    old_nodes_orm = (
        db.query(Node)
        .filter(Node.document_id == document_id, Node.version_id == latest.id)
        .all()
    )
    old_nodes = [_node_to_dict(n) for n in old_nodes_orm]
    old_pmap = _parent_heading_map(db, document_id)

    # Build parent heading map for new nodes from parsed_nodes
    new_node_map = {pn.id: pn for pn in parsed_nodes}
    new_parent_heading: dict[str, str] = {}
    for pn in parsed_nodes:
        if pn.parent_id and pn.parent_id in new_node_map:
            new_parent_heading[pn.id] = new_node_map[pn.parent_id].heading

    # Prepare new node dicts for matching
    new_node_dicts: list[dict] = []
    for pn in parsed_nodes:
        new_node_dicts.append(
            {
                "id": pn.id,
                "heading": pn.heading,
                "section_number": pn.section_number,
                "parent_id": pn.parent_id,
                "level": pn.level,
                "content_hash": compute_content_hash(pn.heading, pn.body_text),
                "_parent_heading": new_parent_heading.get(pn.id, ""),
            }
        )

    # Run matching
    matches = match_nodes(old_nodes, new_node_dicts, old_pmap)

    # Persist new nodes with logical_node_id and version_id
    node_count = 0
    for pn, match in zip(parsed_nodes, matches):
        db_node = Node(
            id=pn.id,
            document_id=document_id,
            version_id=new_version_id,
            parent_id=pn.parent_id,
            logical_node_id=match.logical_node_id,
            heading=pn.heading,
            level=pn.level,
            body_text=pn.body_text,
            page_number=pn.page_number,
            section_number=pn.section_number,
            content_hash=compute_content_hash(pn.heading, pn.body_text),
            node_type=pn.node_type,
        )
        db.add(db_node)
        node_count += 1

    db.commit()

    logger.info(
        "Created version %d for document %s (%d nodes, %d matched)",
        new_version_number,
        document_id,
        node_count,
        sum(1 for m in matches if not m.is_new),
    )

    return {
        "version_id": new_version_id,
        "version_number": new_version_number,
        "node_count": node_count,
        "matches": [
            {
                "logical_node_id": m.logical_node_id,
                "old_node_id": m.old_node_id,
                "new_node_id": m.new_node_id,
                "is_new": m.is_new,
                "score": m.score,
            }
            for m in matches
        ],
    }


def get_version_history(db: Session, document_id: str) -> list[dict]:
    """Retrieve the version history for a document.

    Args:
        db: Active session.
        document_id: The document to query.

    Returns:
        List of version dicts ordered by version number.
    """
    versions = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number)
        .all()
    )
    return [
        {
            "version_id": v.id,
            "version_number": v.version_number,
            "label": v.label,
            "is_latest": v.is_latest,
            "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
        }
        for v in versions
    ]


def get_node_changes(
    db: Session,
    node_id: str,
) -> dict | None:
    """Get change history for a specific logical node.

    Finds the node by ID, resolves its logical_node_id, then compares
    the two most recent versions that contain this logical node.

    Args:
        db: Active session.
        node_id: The node ID to inspect.

    Returns:
        Dict with old/new hashes, summaries, and impact, or None.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if node is None:
        return None

    logical_id = node.logical_node_id or node.id

    # Find all versions that contain this logical node
    all_versions = (
        db.query(Node)
        .filter(
            Node.document_id == node.document_id,
            Node.logical_node_id == logical_id,
        )
        .order_by(Node.created_at)
        .all()
    )

    if len(all_versions) < 2:
        return {
            "logical_node_id": logical_id,
            "heading": node.heading,
            "old_hash": None,
            "new_hash": node.content_hash,
            "change_type": "added",
            "summaries": [],
            "impact_level": None,
        }

    old_node_orm = all_versions[-2]
    new_node_orm = all_versions[-1]

    old_dict = _node_to_dict(old_node_orm)
    new_dict = _node_to_dict(new_node_orm)

    # Determine changed fields
    changed_fields = []
    summaries = []
    for fld in ("heading", "body_text", "level", "section_number"):
        old_val = str(old_dict.get(fld, ""))
        new_val = str(new_dict.get(fld, ""))
        if old_val != new_val:
            changed_fields.append(
                {"field_name": fld, "old_value": old_val, "new_value": new_val}
            )
            label = fld.replace("_", " ").title()
            summaries.append(f"{label}: {old_val} → {new_val}")

    change_type = "modified" if changed_fields else "unchanged"

    # Classify impact
    impact = None
    if change_type == "modified":
        impact = classify_impact(
            heading=new_dict["heading"],
            body_text=new_dict.get("body_text", ""),
            changed_fields=changed_fields,
        ).value

    return {
        "logical_node_id": logical_id,
        "heading": new_dict["heading"],
        "old_hash": old_dict["content_hash"],
        "new_hash": new_dict["content_hash"],
        "change_type": change_type,
        "changed_fields": changed_fields,
        "summaries": summaries,
        "impact_level": impact,
    }
