"""Logical node matching across document versions.

Matching Strategy
-----------------
Nodes across versions are matched using a weighted multi-factor heuristic:

1. **Heading similarity** (weight 0.35)
   Levenshtein-style normalized similarity between heading texts.

2. **Section numbering** (weight 0.30)
   Exact match of section numbers (e.g. "1.2.3").

3. **Parent heading context** (weight 0.20)
   Whether both nodes share the same parent heading text.

4. **Tree position** (weight 0.15)
   Same depth level within the document tree.

A combined score >= MATCH_THRESHOLD (0.55) reuses the existing
``logical_node_id``.  Below the threshold a brand-new logical node is
created.  This avoids fragile single-factor matching while still being
lenient enough for minor rewording between versions.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

MATCH_THRESHOLD: float = 0.55

# Factor weights — must sum to 1.0
W_HEADING: float = 0.35
W_SECTION: float = 0.30
W_PARENT: float = 0.20
W_POSITION: float = 0.15


@dataclass
class MatchCandidate:
    """A node from the old version that is a potential match."""

    node_id: str
    logical_node_id: str
    heading: str
    section_number: str | None
    parent_heading: str
    level: int
    content_hash: str
    score: float = 0.0


@dataclass
class MatchResult:
    """Outcome of matching a new node against old-version candidates."""

    new_node_id: str
    matched: bool
    logical_node_id: str
    old_node_id: str | None = None
    score: float = 0.0
    is_new: bool = False


def _heading_similarity(a: str, b: str) -> float:
    """Normalized heading similarity using SequenceMatcher.

    Args:
        a: First heading.
        b: Second heading.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _section_number_match(a: str | None, b: str | None) -> float:
    """Exact match score for section numbering.

    Args:
        a: Section number from node A.
        b: Section number from node B.

    Returns:
        1.0 on exact match, 0.0 otherwise.
    """
    if a is None and b is None:
        return 1.0
    if a is None or b is None:
        return 0.0
    return 1.0 if a == b else 0.0


def _parent_heading_match(a: str, b: str) -> float:
    """Similarity between parent heading texts.

    Args:
        a: Parent heading of node A.
        b: Parent heading of node B.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _position_match(level_a: int, level_b: int) -> float:
    """Score based on tree depth alignment.

    Args:
        level_a: Tree level of node A.
        level_b: Tree level of node B.

    Returns:
        1.0 if same level, decreasing for each level apart.
    """
    diff = abs(level_a - level_b)
    return max(0.0, 1.0 - diff * 0.25)


def _compute_match_score(
    candidate: MatchCandidate,
    new_heading: str,
    new_section: str | None,
    new_parent_heading: str,
    new_level: int,
) -> float:
    """Compute weighted match score for a candidate.

    Args:
        candidate: The old-version candidate.
        new_heading: Heading of the new node.
        new_section: Section number of the new node.
        new_parent_heading: Parent heading of the new node.
        new_level: Tree level of the new node.

    Returns:
        Weighted score in [0.0, 1.0].
    """
    s_heading = _heading_similarity(candidate.heading, new_heading)
    s_section = _section_number_match(candidate.section_number, new_section)
    s_parent = _parent_heading_match(candidate.parent_heading, new_parent_heading)
    s_position = _position_match(candidate.level, new_level)

    score = (
        W_HEADING * s_heading
        + W_SECTION * s_section
        + W_PARENT * s_parent
        + W_POSITION * s_position
    )
    return round(score, 4)


def match_nodes(
    old_nodes: list[dict],
    new_nodes: list[dict],
    old_parent_map: dict[str, str] | None = None,
) -> list[MatchResult]:
    """Match new-version nodes against old-version nodes.

    Each ``dict`` in the lists is expected to contain:
    ``id``, ``heading``, ``section_number``, ``parent_id``, ``level``,
    ``content_hash``, and optionally ``logical_node_id``.

    ``old_parent_map`` maps old node IDs to their parent heading text.
    If ``None``, parent heading is treated as empty.

    Args:
        old_nodes: Nodes from the previous version.
        new_nodes: Nodes from the newly uploaded version.
        old_parent_map: Maps old node ID → parent heading text.

    Returns:
        List of MatchResult, one per new node.
    """
    if old_parent_map is None:
        old_parent_map = {}

    # Build candidate lookup from old nodes
    candidates: list[MatchCandidate] = []
    for n in old_nodes:
        candidates.append(
            MatchCandidate(
                node_id=n["id"],
                logical_node_id=n.get("logical_node_id") or n["id"],
                heading=n["heading"],
                section_number=n.get("section_number"),
                parent_heading=old_parent_map.get(n["parent_id"], ""),
                level=n["level"],
                content_hash=n.get("content_hash", ""),
            )
        )

    results: list[MatchResult] = []

    for new in new_nodes:
        new_parent_heading = new.get("_parent_heading", "")
        best_candidate: MatchCandidate | None = None
        best_score = 0.0

        for cand in candidates:
            score = _compute_match_score(
                cand,
                new["heading"],
                new.get("section_number"),
                new_parent_heading,
                new["level"],
            )
            if score > best_score:
                best_score = score
                best_candidate = cand

        if best_candidate and best_score >= MATCH_THRESHOLD:
            results.append(
                MatchResult(
                    new_node_id=new["id"],
                    matched=True,
                    logical_node_id=best_candidate.logical_node_id,
                    old_node_id=best_candidate.node_id,
                    score=best_score,
                    is_new=False,
                )
            )
            logger.debug(
                "Matched %s → %s (score=%.3f)",
                new["heading"],
                best_candidate.heading,
                best_score,
            )
        else:
            new_lid = str(uuid.uuid4())
            results.append(
                MatchResult(
                    new_node_id=new["id"],
                    matched=False,
                    logical_node_id=new_lid,
                    score=best_score,
                    is_new=True,
                )
            )
            logger.debug(
                "No match for '%s' (best=%.3f), created logical node",
                new["heading"],
                best_score,
            )

    matched_count = sum(1 for r in results if not r.is_new)
    logger.info(
        "Matching complete: %d/%d matched", matched_count, len(results)
    )
    return results
