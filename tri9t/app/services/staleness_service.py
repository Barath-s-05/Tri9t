"""Document staleness detection service.

Compares stored generation metadata against current document state
to determine whether a QA test-case generation is still valid or
needs regeneration due to document changes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from tri9t.app.db.mongo import get_generations_collection
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.services.selection_service import get_selection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------


class StalenessStatus(str, Enum):
    """Possible staleness states for a generation."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    PARTIALLY_STALE = "PARTIALLY_STALE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class StalenessResult:
    """Structured output of a staleness check."""

    status: StalenessStatus
    reason: str
    changed_nodes: list[dict] = field(default_factory=list)
    changed_sections: list[str] = field(default_factory=list)
    impact_level: str | None = None
    recommendation: str = ""
    stored_version_id: str = ""
    latest_version_id: str = ""
    latest_version_number: int = 0
    total_nodes: int = 0
    changed_count: int = 0

    def to_dict(self) -> dict:
        """Serialize to a JSON-friendly dict."""
        return {
            "status": self.status.value,
            "reason": self.reason,
            "changed_nodes": self.changed_nodes,
            "changed_sections": self.changed_sections,
            "impact_level": self.impact_level,
            "recommendation": self.recommendation,
            "stored_version_id": self.stored_version_id,
            "latest_version_id": self.latest_version_id,
            "latest_version_number": self.latest_version_number,
            "total_nodes": self.total_nodes,
            "changed_count": self.changed_count,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_generation_doc(generation_id: str) -> dict | None:
    """Fetch a generation document from MongoDB.

    Args:
        generation_id: The generation UUID.

    Returns:
        The generation document or None.
    """
    try:
        return get_generations_collection().find_one(
            {"_id": generation_id}, {"_id": 0}
        )
    except Exception as exc:
        logger.error("MongoDB read failed: %s", exc)
        return None


def _get_current_nodes(db: Session, node_ids: list[str]) -> dict[str, Node]:
    """Load current nodes from SQLite and return as a map.

    Args:
        db: Active SQLAlchemy session.
        node_ids: List of node IDs to fetch.

    Returns:
        Dict mapping node_id → Node ORM instance.
    """
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    return {n.id: n for n in nodes}


def _get_latest_version(
    db: Session, document_id: str
) -> DocumentVersion | None:
    """Find the latest version of a document.

    Args:
        db: Active SQLAlchemy session.
        document_id: The document ID.

    Returns:
        The latest DocumentVersion, or None.
    """
    return (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )


def _find_document_id_for_version(
    db: Session, version_id: str
) -> str | None:
    """Resolve a version_id to its parent document_id.

    Args:
        db: Active SQLAlchemy session.
        version_id: The document version ID.

    Returns:
        The document_id string, or None.
    """
    dv = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.id == version_id)
        .first()
    )
    return dv.document_id if dv else None


def _compare_hashes(
    stored_hashes: list[str],
    current_nodes: dict[str, Node],
    node_ids: list[str],
) -> tuple[list[dict], list[str]]:
    """Compare stored node hashes against current state.

    Args:
        stored_hashes: The hash list stored at generation time.
        current_nodes: Map of current node_id → Node.
        node_ids: Ordered list of node IDs.

    Returns:
        Tuple of (changed_nodes, changed_sections).
    """
    changed_nodes: list[dict] = []
    changed_sections: list[str] = []

    for idx, node_id in enumerate(node_ids):
        stored_hash = stored_hashes[idx] if idx < len(stored_hashes) else None
        current_node = current_nodes.get(node_id)

        if current_node is None:
            changed_nodes.append({
                "node_id": node_id,
                "heading": None,
                "change_type": "removed",
                "old_hash": stored_hash,
                "new_hash": None,
            })
            changed_sections.append(f"Node {node_id} (removed)")
            continue

        current_hash = current_node.content_hash
        if stored_hash != current_hash:
            change_type = "modified" if stored_hash else "unknown"
            changed_nodes.append({
                "node_id": node_id,
                "heading": current_node.heading,
                "change_type": change_type,
                "old_hash": stored_hash,
                "new_hash": current_hash,
                "section_number": current_node.section_number,
            })
            label = current_node.heading or node_id
            if current_node.section_number:
                label = f"Section {current_node.section_number}: {label}"
            changed_sections.append(label)

    return changed_nodes, changed_sections


def _determine_impact(changed_nodes: list[dict]) -> str:
    """Determine the overall impact level from changed nodes.

    Uses a simple aggregation: if any node is CRITICAL, the overall
    impact is CRITICAL, otherwise the highest level present wins.

    Args:
        changed_nodes: List of changed node dicts.

    Returns:
        Impact level string (LOW, MEDIUM, HIGH, CRITICAL).
    """
    from tri9t.app.services.impact_analyzer import (
        ImpactLevel,
        classify_impact,
    )

    if not changed_nodes:
        return ImpactLevel.LOW.value

    highest = ImpactLevel.LOW
    for cn in changed_nodes:
        if cn.get("change_type") == "removed":
            level = ImpactLevel.HIGH
        else:
            changed_fields = []
            if cn.get("old_hash") != cn.get("new_hash"):
                changed_fields.append({
                    "field_name": "content_hash",
                    "old_value": cn.get("old_hash", ""),
                    "new_value": cn.get("new_hash", ""),
                })
            level = classify_impact(
                heading=cn.get("heading", ""),
                body_text="",
                changed_fields=changed_fields,
            )

        priority = {ImpactLevel.LOW: 0, ImpactLevel.MEDIUM: 1, ImpactLevel.HIGH: 2, ImpactLevel.CRITICAL: 3}
        if priority.get(level, 0) > priority.get(highest, 0):
            highest = level

    return highest.value


def _build_reason(changed_sections: list[str], changed_count: int, total: int) -> str:
    """Build a human-readable staleness reason.

    Args:
        changed_sections: List of changed section labels.
        changed_count: Number of changed nodes.
        total: Total number of nodes.

    Returns:
        Reason string.
    """
    if changed_count == 0:
        return "All nodes match stored hashes"

    sections = ", ".join(changed_sections[:5])
    if len(changed_sections) > 5:
        sections += f" and {len(changed_sections) - 5} more"

    return f"{changed_count}/{total} node(s) changed: {sections}"


def _build_recommendation(status: StalenessStatus, impact_level: str | None) -> str:
    """Build a recommendation based on staleness status.

    Args:
        status: The determined staleness status.
        impact_level: The overall impact level.

    Returns:
        Recommendation string.
    """
    if status == StalenessStatus.CURRENT:
        return "No action needed - generation is current"

    if status == StalenessStatus.UNKNOWN:
        return "Unable to determine staleness - manual review recommended"

    if status == StalenessStatus.STALE:
        return "Regenerate QA test cases - document has changed significantly"

    # PARTIAL_STALE
    if impact_level in ("HIGH", "CRITICAL"):
        return "Regenerate QA test cases - critical sections have changed"

    return "Consider regenerating - some sections have changed"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_staleness(
    db: Session,
    generation_id: str,
) -> StalenessResult:
    """Check whether a generation is still current.

    Compares the stored ``node_hashes`` from the generation document
    against the current state of those nodes in SQLite.

    Args:
        db: Active SQLAlchemy session.
        generation_id: The generation UUID.

    Returns:
        A ``StalenessResult`` with status, reason, and details.
    """
    gen_doc = _get_generation_doc(generation_id)
    if gen_doc is None:
        return StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="Generation not found",
        )

    stored_version_id = gen_doc.get("version_id", "")
    stored_hashes = gen_doc.get("node_hashes", [])

    # We need the node_ids — these were the selection's node_ids
    # The generation doc doesn't store them directly, so we look up
    # the selection to get the node_ids.
    selection_id = gen_doc.get("selection_id", "")

    selection = get_selection(db, selection_id)
    if selection is None:
        return StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="Selection not found for this generation",
            stored_version_id=stored_version_id,
        )

    node_ids = selection.get("node_ids", [])
    if not node_ids:
        return StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="Selection has no nodes",
            stored_version_id=stored_version_id,
        )

    # Load current nodes
    current_nodes = _get_current_nodes(db, node_ids)

    # Find the latest version
    document_id = _find_document_id_for_version(db, stored_version_id)
    if document_id is None:
        return StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="Cannot resolve document for stored version",
            stored_version_id=stored_version_id,
        )

    latest = _get_latest_version(db, document_id)
    if latest is None:
        return StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="No versions found for document",
            stored_version_id=stored_version_id,
        )

    latest_version_id = latest.id
    latest_version_number = latest.version_number

    # Compare hashes
    total_nodes = len(node_ids)
    changed_nodes, changed_sections = _compare_hashes(
        stored_hashes, current_nodes, node_ids
    )
    changed_count = len(changed_nodes)

    # Determine status
    if changed_count == 0:
        status = StalenessStatus.CURRENT
    elif changed_count == total_nodes:
        status = StalenessStatus.STALE
    else:
        status = StalenessStatus.PARTIALLY_STALE

    # If the stored version is not the latest, mark as stale
    if stored_version_id != latest_version_id and status == StalenessStatus.CURRENT:
        status = StalenessStatus.PARTIALLY_STALE

    impact_level = _determine_impact(changed_nodes) if changed_nodes else None
    reason = _build_reason(changed_sections, changed_count, total_nodes)
    recommendation = _build_recommendation(status, impact_level)

    result = StalenessResult(
        status=status,
        reason=reason,
        changed_nodes=changed_nodes,
        changed_sections=changed_sections,
        impact_level=impact_level,
        recommendation=recommendation,
        stored_version_id=stored_version_id,
        latest_version_id=latest_version_id,
        latest_version_number=latest_version_number,
        total_nodes=total_nodes,
        changed_count=changed_count,
    )

    logger.info(
        "Staleness check for %s: %s (%d/%d changed)",
        generation_id,
        status.value,
        changed_count,
        total_nodes,
    )
    return result
