"""Retry engine for LLM calls with validation.

Wraps an async LLM callable with automatic retry on validation
failure or provider error.  Reports events via an optional
callback so callers can wire in audit logging without coupling.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def execute_with_retry(
    func: Callable,
    validator: Callable,
    max_retries: int = MAX_RETRIES,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> tuple[str, list[dict], int]:
    """Execute *func* with retry and validation.

    Args:
        func: Async callable returning the raw LLM response string.
        validator: Callable taking a string and returning a
            ``ValidationResult`` with ``is_valid`` and ``test_cases``.
        max_retries: Maximum number of retry attempts (total
            calls = ``max_retries + 1``).
        on_event: Optional callback ``(event_type, details)`` invoked
            on validation failures and retries.

    Returns:
        ``(raw_output, test_cases, retry_count)`` where
        ``retry_count`` is the number of *retries* (0 on first success).

    Raises:
        Exception: If all attempts fail.
    """
    last_error: str = ""

    for attempt in range(max_retries + 1):
        try:
            raw_output = await func()
            result = validator(raw_output)

            if result.is_valid:
                return raw_output, result.test_cases, attempt

            last_error = "; ".join(result.errors)
            logger.warning(
                "Attempt %d/%d validation failed: %s",
                attempt + 1,
                max_retries + 1,
                last_error,
            )
            if on_event is not None:
                on_event(
                    "validation_failed",
                    {"attempt": attempt + 1, "errors": result.errors},
                )

        except Exception as exc:
            last_error = str(exc)
            logger.warning(
                "Attempt %d/%d raised: %s",
                attempt + 1,
                max_retries + 1,
                last_error,
            )
            if on_event is not None:
                on_event(
                    "validation_failed",
                    {"attempt": attempt + 1, "errors": [last_error]},
                )

        # Schedule a retry if we have attempts left
        if attempt < max_retries:
            logger.info(
                "Retrying (attempt %d/%d)…",
                attempt + 2,
                max_retries + 1,
            )
            if on_event is not None:
                on_event(
                    "retry_attempt",
                    {
                        "attempt": attempt + 1,
                        "max_retries": max_retries,
                        "reason": last_error,
                    },
                )

    raise Exception(
        f"All {max_retries + 1} attempts failed. Last error: {last_error}"
    )
