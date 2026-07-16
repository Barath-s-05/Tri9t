"""Validation of LLM-generated test case outputs.

Ensures the LLM response is valid JSON conforming to the expected
schema, and contains between ``MIN_TEST_CASES`` and
``MAX_TEST_CASES`` entries.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_TEST_CASES = 3
MAX_TEST_CASES = 5

VALID_PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})

REQUIRED_FIELDS = frozenset(
    {"title", "preconditions", "steps", "expected_result",
     "priority", "traceability"}
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """Outcome of output validation."""

    is_valid: bool
    errors: list[str]
    test_cases: list[dict] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_markdown(text: str) -> str:
    """Remove wrapping markdown code-fences (```json … ```)."""
    text = text.strip()
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[: -3].rstrip()
    return text.strip()


def _validate_count(cases: list) -> list[str]:
    errors: list[str] = []
    if len(cases) < MIN_TEST_CASES:
        errors.append(
            f"Too few test cases: {len(cases)} (minimum {MIN_TEST_CASES})"
        )
    if len(cases) > MAX_TEST_CASES:
        errors.append(
            f"Too many test cases: {len(cases)} (maximum {MAX_TEST_CASES})"
        )
    return errors


def _validate_case(idx: int, tc: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(tc, dict):
        return [f"Test case {idx} is not a JSON object"]

    missing = REQUIRED_FIELDS - set(tc.keys())
    if missing:
        errors.append(f"Test case {idx} missing fields: {sorted(missing)}")
        return errors  # can't check further

    for field in REQUIRED_FIELDS:
        value = tc[field]
        if field in ("steps", "traceability"):
            if not isinstance(value, list):
                errors.append(
                    f"Test case {idx}: '{field}' must be a list"
                )
        elif field == "priority":
            if not isinstance(value, str) or value.upper() not in VALID_PRIORITIES:
                errors.append(
                    f"Test case {idx}: 'priority' must be one of {sorted(VALID_PRIORITIES)}"
                )
        elif isinstance(value, str) and not value.strip():
            errors.append(f"Test case {idx}: '{field}' is empty")

    return errors


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_output(raw_output: str) -> ValidationResult:
    """Validate a raw LLM response string.

    Steps:
        1. Strip markdown fences if present.
        2. Parse JSON.
        3. Verify ``test_cases`` key exists and is a list.
        4. Check count bounds (3–5).
        5. Validate required fields on each case.

    Returns:
        A ``ValidationResult`` with ``is_valid``, ``errors``, and
        optionally the parsed ``test_cases`` list.
    """
    cleaned = _strip_markdown(raw_output)

    # 1. JSON parse
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return ValidationResult(
            is_valid=False, errors=[f"Invalid JSON: {exc}"]
        )

    # 2. Top-level key
    if "test_cases" not in data:
        return ValidationResult(
            is_valid=False, errors=["Missing 'test_cases' key"]
        )

    cases = data["test_cases"]
    if not isinstance(cases, list):
        return ValidationResult(
            is_valid=False, errors=["'test_cases' must be a list"]
        )

    # 3. Count
    errors = _validate_count(cases)

    # 4. Per-case validation
    for i, tc in enumerate(cases, start=1):
        errors.extend(_validate_case(i, tc))

    if errors:
        return ValidationResult(is_valid=False, errors=errors)

    return ValidationResult(is_valid=True, errors=[], test_cases=cases)
