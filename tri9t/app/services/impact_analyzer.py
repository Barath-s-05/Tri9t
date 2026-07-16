"""Impact analysis for document changes.

Classifies each MODIFIED node change into an impact level:

    LOW       — cosmetic / typo / formatting
    MEDIUM    — content changes (battery capacity, values)
    HIGH      — measurement thresholds, parameters
    CRITICAL  — safety behaviour, emergency procedures

Rules are configurable via ``ImpactRule`` objects.  The default ruleset
covers common technical-document scenarios and can be extended at
runtime.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ImpactLevel(str, Enum):
    """Severity classification for a change."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class ImpactRule:
    """A single keyword-pattern rule for impact classification.

    Attributes:
        keywords: Terms that trigger this rule (case-insensitive).
        level: The impact level to assign.
        description: Human-readable explanation.
    """

    keywords: list[str]
    level: ImpactLevel
    description: str


# Default ruleset — ordered so CRITICAL rules are checked first.
DEFAULT_RULES: list[ImpactRule] = [
    ImpactRule(
        keywords=[
            "safety", "emergency", "hazard", "danger", "warning",
            "alarm", "shutdown", "fail-safe", "fault", "critical",
            "injury", "death", "fire", "explosion", "toxic",
        ],
        level=ImpactLevel.CRITICAL,
        description="Safety-critical behaviour or emergency procedure",
    ),
    ImpactRule(
        keywords=[
            "threshold", "limit", "pressure", "temperature",
            "voltage", "current", "frequency", "speed", "torque",
            "measurement", "calibration", "tolerance", "accuracy",
            "increment", "decrement", "mmhg", "kpa", "psi", "bar",
        ],
        level=ImpactLevel.HIGH,
        description="Measurement threshold or calibration parameter",
    ),
    ImpactRule(
        keywords=[
            "battery", "capacity", "voltage", "charge", "discharge",
            "runtime", "duration", "cycle", "lifetime", "capacity",
            "power", "watt", "energy", "consumption",
        ],
        level=ImpactLevel.MEDIUM,
        description="Capacity, power, or performance parameter",
    ),
    ImpactRule(
        keywords=[
            "typo", "spelling", "grammar", "formatting",
            "whitespace", "indentation", "capitalization",
        ],
        level=ImpactLevel.LOW,
        description="Cosmetic or formatting change",
    ),
]

# Simple typo detector — looks for single-character changes
_TYPO_RE = re.compile(
    r"(.)\1{2,}", re.IGNORECASE
)  # triple+ repeated chars


def _text_looks_like_typo(old: str, new: str) -> bool:
    """Heuristic: detect if the change is likely a typo fix.

    Classifies a change as a typo when the edit distance is small and
    the differing characters appear to be a letter transposition or
    single-character substitution rather than a numeric value change.

    Args:
        old: Original text.
        new: Modified text.

    Returns:
        True if the change appears cosmetic.
    """
    if old == new:
        return True

    len_diff = abs(len(old) - len(new))
    if len_diff > 2:
        return False

    # For insertion / deletion (length differs): check edge containment
    if len_diff > 0:
        shorter, longer = (old, new) if len(old) < len(new) else (new, old)
        if longer.startswith(shorter) or longer.endswith(shorter):
            return len(longer) <= 30
        return False

    # Same-length strings: count character-level differences
    diff_chars = sum(1 for a, b in zip(old.lower(), new.lower()) if a != b)

    if diff_chars > 2:
        return False

    # If ALL differing characters are digits, this is a value change, not a typo
    differing_old = [a for a, b in zip(old, new) if a != b]
    if differing_old and all(c.isdigit() for c in differing_old):
        return False

    # Alphabetic / mixed diffs with <= 2 changes in text up to 40 chars
    return diff_chars <= 2 and len(old) <= 40


def _match_rules(text: str, rules: list[ImpactRule]) -> ImpactRule | None:
    """Find the first rule whose keywords appear in the text.

    Uses word-boundary regex matching to prevent false positives from
    substring matches (e.g. "fault" matching inside "default").

    Args:
        text: Text to search.
        rules: Ordered list of rules.

    Returns:
        The first matching rule, or None.
    """
    text_lower = text.lower()
    for rule in rules:
        for kw in rule.keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                return rule
    return None


def classify_impact(
    heading: str,
    body_text: str,
    changed_fields: list[dict],
    rules: list[ImpactRule] | None = None,
) -> ImpactLevel:
    """Classify the impact level of a node change.

    Args:
        heading: The node heading.
        body_text: The new body text (used for keyword matching).
        changed_fields: List of ``{field_name, old_value, new_value}`` dicts.
        rules: Custom ruleset (uses DEFAULT_RULES if None).

    Returns:
        The classified ImpactLevel.
    """
    if rules is None:
        rules = DEFAULT_RULES

    combined_text = f"{heading} {body_text}"
    for fc in changed_fields:
        combined_text += f" {fc.get('old_value', '')} {fc.get('new_value', '')}"

    # Check if all changes are typos
    all_typos = True
    for fc in changed_fields:
        if fc["field_name"] in ("heading", "body_text"):
            if not _text_looks_like_typo(
                fc.get("old_value", ""), fc.get("new_value", "")
            ):
                all_typos = False
                break

    if all_typos and changed_fields:
        return ImpactLevel.LOW

    # Keyword-based rule matching (rules ordered CRITICAL → LOW)
    matched_rule = _match_rules(combined_text, rules)
    if matched_rule:
        return matched_rule.level

    # Default for unclassified changes
    return ImpactLevel.MEDIUM


def analyze_impacts(
    diffs: list[dict],
    rules: list[ImpactRule] | None = None,
) -> list[dict]:
    """Analyze a list of diffs and add impact levels.

    Args:
        diffs: List of diff dicts with ``change_type``, ``heading``,
            ``changed_fields``.
        rules: Optional custom ruleset.

    Returns:
        The same list with an ``impact_level`` key added to each dict.
    """
    results: list[dict] = []
    for diff in diffs:
        entry = dict(diff)
        if diff.get("change_type") == "modified":
            entry["impact_level"] = classify_impact(
                heading=diff.get("heading", ""),
                body_text=diff.get("body_text", ""),
                changed_fields=diff.get("changed_fields", []),
                rules=rules,
            ).value
        else:
            entry["impact_level"] = None
        results.append(entry)

    logger.info("Impact analysis complete: %d diffs", len(results))
    return results
