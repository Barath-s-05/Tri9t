"""Audit logging for generation events.

Persists structured events to MongoDB so every generation
lifecycle transition is traceable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from tri9t.app.db.mongo import get_audit_collection

logger = logging.getLogger(__name__)


def log_event(
    event_type: str,
    generation_id: str,
    details: dict | None = None,
) -> None:
    """Record an audit event.

    Event types:
        - ``generation_started``
        - ``prompt_built``
        - ``groq_request_sent``
        - ``groq_response_received``
        - ``validation_failed``
        - ``retry_attempt``
        - ``generation_completed``
        - ``generation_failed``
    """
    doc = {
        "event_type": event_type,
        "generation_id": generation_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": details or {},
    }
    try:
        get_audit_collection().insert_one(doc)
        logger.info("Audit: %s for %s", event_type, generation_id)
    except Exception as exc:
        logger.error("Failed to write audit event: %s", exc)


def get_events(generation_id: str) -> list[dict]:
    """Return all audit events for a generation, ordered by time."""
    try:
        cursor = (
            get_audit_collection()
            .find({"generation_id": generation_id}, {"_id": 0})
            .sort("timestamp", 1)
        )
        return list(cursor)
    except Exception as exc:
        logger.error("Failed to read audit events: %s", exc)
        return []
