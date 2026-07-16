"""Hierarchical tree construction from flat parsed nodes."""

from __future__ import annotations

import logging
import uuid

from tri9t.app.schemas.parser import ParsedNode

logger = logging.getLogger(__name__)


def _infer_level_from_section(section_number: str | None) -> int:
    """Infer heading level from section numbering depth.

    Args:
        section_number: Dot-separated section number like "1.2.3".

    Returns:
        The inferred level based on depth.
    """
    if section_number is None:
        return 1
    return len(section_number.split("."))


def build_tree(nodes: list[ParsedNode]) -> tuple[list[ParsedNode], list[str]]:
    """Build a parent-child hierarchy from a flat list of parsed nodes.

    Uses a stack-based algorithm. Nodes are assigned IDs, and parent_id
    links are established based on heading level. A root node is injected
    if no level-1 heading exists.

    Args:
        nodes: Flat list of ParsedNode objects in document order.

    Returns:
        Tuple of (nodes_with_ids_and_parents, warnings).
    """
    warnings: list[str] = []

    if not nodes:
        return [], warnings

    # Assign unique IDs to all nodes
    for node in nodes:
        if not node.id:
            node.id = str(uuid.uuid4())

    # Ensure there is a root level-1 node
    has_root = any(n.level == 1 for n in nodes)
    if not has_root:
        root = ParsedNode(
            id=str(uuid.uuid4()),
            heading="Root",
            level=1,
            body_text="",
            page_number=nodes[0].page_number if nodes else 1,
            node_type="root",
        )
        nodes.insert(0, root)
        warnings.append("No level-1 heading found; injected artificial root node")

    # Stack-based tree building
    stack: list[ParsedNode] = []
    result: list[ParsedNode] = []

    for node in nodes:
        # Pop stack until we find a valid parent (level < current)
        while stack and stack[-1].level >= node.level:
            stack.pop()

        if stack:
            node.parent_id = stack[-1].id
        else:
            node.parent_id = None

        stack.append(node)
        result.append(node)

    logger.info("Tree built: %d nodes, %d warnings", len(result), len(warnings))
    return result, warnings
