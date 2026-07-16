"""Validation of parsed document tree structure."""

from __future__ import annotations

import logging
from collections import Counter

from tri9t.app.schemas.parser import ParsedNode

logger = logging.getLogger(__name__)


def validate_tree(nodes: list[ParsedNode]) -> list[str]:
    """Validate a parsed tree for structural and content issues.

    Checks for:
    - Duplicate headings
    - Skipped heading levels
    - Orphan nodes (non-root nodes without a parent)
    - Empty headings
    - Missing body text
    - Invalid numbering
    - Mixed numbering styles

    Args:
        nodes: List of ParsedNode objects with parent_id set.

    Returns:
        List of warning messages (empty if tree is clean).
    """
    warnings: list[str] = []

    if not nodes:
        return warnings

    node_map = {n.id: n for n in nodes}

    # --- Duplicate headings ---
    heading_counts: Counter[str] = Counter()
    for node in nodes:
        heading_counts[node.heading] += 1

    for heading, count in heading_counts.items():
        if count > 1:
            warnings.append(f"Duplicate heading '{heading}'")

    # --- Skipped heading levels ---
    for node in nodes:
        if node.parent_id and node.parent_id in node_map:
            parent = node_map[node.parent_id]
            if node.level > parent.level + 1:
                warnings.append(
                    f"Skipped heading level: {parent.heading} (L{parent.level}) "
                    f"→ {node.heading} (L{node.level})"
                )

    # --- Orphan nodes (non-root without parent) ---
    for node in nodes:
        if node.parent_id is None and node.level != 1:
            pass  # Root-level nodes without parent are acceptable
        elif node.parent_id and node.parent_id not in node_map:
            warnings.append(f"Orphan node '{node.heading}' references missing parent")

    # --- Empty headings ---
    for node in nodes:
        if not node.heading.strip():
            warnings.append(f"Empty heading on node (page {node.page_number})")

    # --- Missing body ---
    for node in nodes:
        if not node.body_text.strip() and node.node_type != "root":
            warnings.append(f"Missing body text for heading '{node.heading}'")

    # --- Numbering checks ---
    numbered_nodes = [n for n in nodes if n.section_number is not None]
    if numbered_nodes:
        _check_numbering_consistency(numbered_nodes, warnings)

    logger.info("Validation complete: %d warnings", len(warnings))
    return warnings


def _check_numbering_consistency(
    nodes: list[ParsedNode],
    warnings: list[str],
) -> None:
    """Check section numbering for jumps, mixed styles, and invalid patterns.

    Args:
        nodes: Nodes that have section numbers.
        warnings: Accumulator list for warning messages.
    """
    section_parts: list[list[str]] = []
    for node in nodes:
        parts = node.section_number.split(".")
        section_parts.append(parts)

    # Detect numbering style mixing (e.g., "1.A" vs "1.2")
    styles: set[str] = set()
    for parts in section_parts:
        for part in parts:
            if part.isdigit():
                styles.add("numeric")
            elif part.isalpha():
                styles.add("alpha")

    if len(styles) > 1:
        warnings.append("Mixed numbering styles detected (numeric and alpha)")

    # Detect numbering jumps at same depth
    depth_groups: dict[int, list[tuple[int, str]]] = {}
    for idx, parts in enumerate(section_parts):
        depth = len(parts)
        if depth not in depth_groups:
            depth_groups[depth] = []
        try:
            last_part = int(parts[-1])
            depth_groups[depth].append((last_part, ".".join(parts)))
        except ValueError:
            continue

    for depth, entries in depth_groups.items():
        for i in range(1, len(entries)):
            prev_num, prev_label = entries[i - 1]
            curr_num, curr_label = entries[i]
            if curr_num != prev_num + 1 and curr_num != prev_num:
                warnings.append(
                    f"Section numbering jumps from {prev_label} to {curr_label}"
                )
