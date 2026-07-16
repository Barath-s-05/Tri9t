"""Parser report generation and formatting."""

from __future__ import annotations

import logging
import time

from tri9t.app.schemas.parser import ParserReport

logger = logging.getLogger(__name__)


class Timer:
    """Context manager for measuring execution time in milliseconds."""

    def __init__(self) -> None:
        self.start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000


def build_report(
    *,
    pages_processed: int,
    nodes_created: int,
    headings_detected: int,
    tables_detected: int,
    lists_detected: int,
    warnings: list[str],
    errors: list[str] | None = None,
    processing_time_ms: float = 0.0,
) -> ParserReport:
    """Construct a ParserReport with the given metrics.

    Args:
        pages_processed: Number of PDF pages processed.
        nodes_created: Total tree nodes created.
        headings_detected: Number of headings found.
        tables_detected: Number of table regions found.
        lists_detected: Number of list items found.
        warnings: Accumulated warning messages.
        errors: Accumulated error messages.
        processing_time_ms: Total processing time in ms.

    Returns:
        A populated ParserReport instance.
    """
    report = ParserReport(
        pages_processed=pages_processed,
        nodes_created=nodes_created,
        headings_detected=headings_detected,
        tables_detected=tables_detected,
        lists_detected=lists_detected,
        warnings=warnings,
        errors=errors or [],
        processing_time_ms=round(processing_time_ms, 2),
    )

    logger.info(
        "Report: %d pages, %d nodes, %d warnings",
        pages_processed,
        nodes_created,
        len(warnings),
    )
    return report
