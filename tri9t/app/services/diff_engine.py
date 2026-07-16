"""Semantic document comparison engine.

Compares matched nodes across two document versions and classifies each
node as ADDED, REMOVED, MODIFIED, or UNCHANGED.  For MODIFIED nodes
it produces human-readable summaries and lists of changed fields.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ChangeType(str, Enum):
    """Classification of a node-level change."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class FieldChange:
    """Describes a single changed field between versions."""

    field_name: str
    old_value: str
    new_value: str


@dataclass
class NodeDiff:
    """Diff result for a single logical node across two versions."""

    logical_node_id: str
    heading: str
    change_type: ChangeType
    old_hash: str
    new_hash: str
    changed_fields: list[FieldChange] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)


def _summarize_field_change(fc: FieldChange) -> str:
    """Generate a human-readable one-liner for a field change.

    Args:
        fc: A FieldChange instance.

    Returns:
        A short descriptive string.
    """
    old = fc.old_value.strip() if fc.old_value else "(empty)"
    new = fc.new_value.strip() if fc.new_value else "(empty)"

    # Truncate long values
    if len(old) > 80:
        old = old[:77] + "..."
    if len(new) > 80:
        new = new[:77] + "..."

    label = fc.field_name.replace("_", " ").title()
    return f"{label}: {old} → {new}"


def _extract_value_change(body: str) -> str | None:
    """Try to extract a numeric / threshold value change from body text.

    Looks for patterns like ``Battery threshold: 15%`` or ``Limit: 200 kPa``
    and returns a short summary.

    Args:
        body: The body text.

    Returns:
        Summary string or None.
    """
    pattern = re.compile(
        r"([A-Za-z ]+?)(?:\s*[:=]\s*)(\d+[\.,]?\d*\s*\w*)", re.IGNORECASE
    )
    matches = pattern.findall(body)
    if matches:
        label, value = matches[0]
        return f"{label.strip()}: {value.strip()}"
    return None


def _generate_body_summary(old_body: str, new_body: str) -> list[str]:
    """Produce human-readable summaries for body text changes.

    Attempts to extract structured value changes.  Falls back to a
    generic length-based summary.

    Args:
        old_body: Body text from old version.
        new_body: Body text from new version.

    Returns:
        List of summary strings.
    """
    summaries: list[str] = []

    old_val = _extract_value_change(old_body)
    new_val = _extract_value_change(new_body)

    if old_val and new_val:
        summaries.append(f"{old_val} → {new_val}")
    elif old_body.strip() != new_body.strip():
        old_len = len(old_body.strip())
        new_len = len(new_body.strip())
        diff = new_len - old_len
        direction = "expanded" if diff > 0 else "shrunk"
        summaries.append(f"Content {direction} ({old_len} → {new_len} chars)")

    return summaries


def compute_diff(
    matched_pairs: list[dict],
    old_node_map: dict[str, dict],
    new_node_map: dict[str, dict],
) -> list[NodeDiff]:
    """Compare two versions using matched logical node pairs.

    Args:
        matched_pairs: List of dicts with ``logical_node_id``,
            ``old_node_id`` (may be None), ``new_node_id``.
        old_node_map: Maps old node ID → full node dict.
        new_node_map: Maps new node ID → full node dict.

    Returns:
        List of NodeDiff objects.
    """
    diffs: list[NodeDiff] = []
    seen_logical: set[str] = set()

    for pair in matched_pairs:
        lid = pair["logical_node_id"]
        old_id = pair.get("old_node_id")
        new_id = pair["new_node_id"]
        seen_logical.add(lid)

        old = old_node_map.get(old_id, {}) if old_id else {}
        new = new_node_map.get(new_id, {})

        old_hash = old.get("content_hash", "")
        new_hash = new.get("content_hash", "")

        # ADDED node — present only in new version
        if not old_id or not old:
            diff = NodeDiff(
                logical_node_id=lid,
                heading=new.get("heading", ""),
                change_type=ChangeType.ADDED,
                old_hash="",
                new_hash=new_hash,
            )
            diffs.append(diff)
            continue

        # REMOVED node — present only in old version
        if not new_id or not new:
            diff = NodeDiff(
                logical_node_id=lid,
                heading=old.get("heading", ""),
                change_type=ChangeType.REMOVED,
                old_hash=old_hash,
                new_hash="",
            )
            diffs.append(diff)
            continue

        # UNCHANGED
        if old_hash == new_hash:
            diff = NodeDiff(
                logical_node_id=lid,
                heading=new.get("heading", ""),
                change_type=ChangeType.UNCHANGED,
                old_hash=old_hash,
                new_hash=new_hash,
            )
            diffs.append(diff)
            continue

        # MODIFIED — compute field-level changes
        changed_fields: list[FieldChange] = []

        for fld in ("heading", "body_text", "level", "section_number"):
            old_val = str(old.get(fld, ""))
            new_val = str(new.get(fld, ""))
            if old_val != new_val:
                changed_fields.append(
                    FieldChange(
                        field_name=fld,
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

        summaries: list[str] = []
        for fc in changed_fields:
            summaries.append(_summarize_field_change(fc))

        # Try to add a value-change summary from body text
        body_summaries = _generate_body_summary(
            old.get("body_text", ""), new.get("body_text", "")
        )
        summaries.extend(body_summaries)

        diff = NodeDiff(
            logical_node_id=lid,
            heading=new.get("heading", ""),
            change_type=ChangeType.MODIFIED,
            old_hash=old_hash,
            new_hash=new_hash,
            changed_fields=changed_fields,
            summaries=summaries,
        )
        diffs.append(diff)

    logger.info("Diff complete: %d nodes compared", len(diffs))
    return diffs
