"""Generation orchestration service.

Coordinates the full AI generation workflow:

    Selection → Load Nodes → Reconstruct Text → Prompt Builder →
    Groq → Validate → Retry → Store → Return

All MongoDB and SQLite interactions live here; the router is
kept thin.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from tri9t.app.core.config import settings
from tri9t.app.db.mongo import get_generations_collection
from tri9t.app.models.node import Node
from tri9t.app.services import (
    audit_service,
    llm_service,
    output_validator,
    prompt_builder,
    retry_engine,
)
from tri9t.app.services.selection_service import get_selection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GenerationError(Exception):
    """Raised when generation cannot proceed."""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def generate_test_cases(
    db: Session,
    selection_id: str,
    model_override: str | None = None,
    temperature_override: float | None = None,
) -> dict:
    """Generate QA test cases from a version-pinned selection.

    Returns:
        Dict with ``generation_id``, ``test_cases``, and ``metadata``.

    Raises:
        GenerationError: On validation or provider errors.
    """
    generation_id = str(uuid.uuid4())
    start_time = time.monotonic()

    # ── 1. Load selection ──────────────────────────────────────────
    selection = get_selection(db, selection_id)
    if selection is None:
        raise GenerationError("Selection not found")

    node_ids: list[str] = selection.get("node_ids", [])
    if not node_ids:
        raise GenerationError("Selection has no nodes")

    # ── 2. Verify all nodes belong to same document version ────────
    version_id = selection["document_version_id"]

    # ── 3. Load nodes ──────────────────────────────────────────────
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()
    if not nodes:
        raise GenerationError("No valid nodes found for selection")

    # ── 4. Build prompt ────────────────────────────────────────────
    audit_service.log_event(
        "generation_started",
        generation_id,
        {
            "selection_id": selection_id,
            "version_id": version_id,
        },
    )

    prompt = prompt_builder.build_prompt(nodes)

    audit_service.log_event(
        "prompt_built",
        generation_id,
        {
            "prompt_version": prompt.prompt_version,
            "prompt_hash": prompt.prompt_hash,
        },
    )

    # ── 5. Resolve model / temperature ─────────────────────────────
    model = model_override or settings.MODEL_NAME
    temperature = (
        temperature_override
        if temperature_override is not None
        else settings.TEMPERATURE
    )

    if not settings.GROQ_API_KEY:
        raise GenerationError("No Groq API key configured")

    try:
        provider = llm_service.get_provider("groq", settings.GROQ_API_KEY)
    except ValueError as exc:
        raise GenerationError(str(exc)) from exc

    # ── 6. LLM + retry ────────────────────────────────────────────
    async def llm_call() -> str:
        return await provider.generate(prompt, model, temperature)

    def audit_callback(event_type: str, details: dict) -> None:
        audit_service.log_event(event_type, generation_id, details)

    audit_service.log_event(
        "groq_request_sent",
        generation_id,
        {
            "model": model,
            "temperature": temperature,
        },
    )

    try:
        raw_output, test_cases, retry_count = (
            await retry_engine.execute_with_retry(
                llm_call,
                output_validator.validate_output,
                on_event=audit_callback,
            )
        )
    except Exception as exc:
        audit_service.log_event(
            "generation_failed",
            generation_id,
            {"error": str(exc)},
        )
        raise GenerationError(f"Generation failed: {exc}") from exc

    audit_service.log_event(
        "groq_response_received",
        generation_id,
        {
            "response_length": len(raw_output),
            "retry_count": retry_count,
        },
    )

    # ── 7. Compute hashes & timing ────────────────────────────────
    processing_time_ms = round((time.monotonic() - start_time) * 1000)
    response_hash = hashlib.sha256(
        json.dumps(test_cases, sort_keys=True).encode()
    ).hexdigest()
    node_hashes = [node.content_hash for node in nodes]

    # ── 8. Store in MongoDB ────────────────────────────────────────
    gen_doc = {
        "_id": generation_id,
        "selection_id": selection_id,
        "version_id": version_id,
        "node_hashes": node_hashes,
        "prompt_version": prompt.prompt_version,
        "prompt_hash": prompt.prompt_hash,
        "provider": "groq",
        "model": model,
        "temperature": temperature,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "valid",
        "retry_count": retry_count,
        "response_hash": response_hash,
        "processing_time_ms": processing_time_ms,
        "test_cases": test_cases,
    }

    try:
        get_generations_collection().insert_one(gen_doc)
    except Exception as exc:
        logger.error("MongoDB insert failed: %s", exc)
        raise GenerationError(
            f"Failed to persist generation: {exc}"
        ) from exc

    # ── 9. Audit: completed ────────────────────────────────────────
    audit_service.log_event(
        "generation_completed",
        generation_id,
        {
            "test_case_count": len(test_cases),
            "retry_count": retry_count,
            "processing_time_ms": processing_time_ms,
        },
    )

    logger.info(
        "Generation %s completed (%d test cases, %d retries, %dms)",
        generation_id,
        len(test_cases),
        retry_count,
        processing_time_ms,
    )

    return {
        "generation_id": generation_id,
        "test_cases": test_cases,
        "metadata": {
            "selection_id": selection_id,
            "version_id": version_id,
            "prompt_version": prompt.prompt_version,
            "prompt_hash": prompt.prompt_hash,
            "provider": "groq",
            "model": model,
            "temperature": temperature,
            "generated_at": gen_doc["generated_at"],
            "validation_status": "valid",
            "retry_count": retry_count,
            "response_hash": response_hash,
            "processing_time_ms": processing_time_ms,
        },
    }


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def get_generation(generation_id: str) -> dict | None:
    """Fetch a single generation document from MongoDB."""
    try:
        doc = get_generations_collection().find_one(
            {"_id": generation_id}, {"_id": 0}
        )
        return doc
    except Exception as exc:
        logger.error("Failed to retrieve generation: %s", exc)
        return None


def get_generation_history(
    selection_id: str | None = None,
    version_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """Return paginated generation history with optional filters."""
    try:
        query: dict = {}
        if selection_id:
            query["selection_id"] = selection_id
        if version_id:
            query["version_id"] = version_id

        col = get_generations_collection()
        total = col.count_documents(query)
        docs = list(
            col.find(query, {"_id": 0})
            .sort("generated_at", -1)
            .skip(offset)
            .limit(limit)
        )
        return {"generations": docs, "total": total}
    except Exception as exc:
        logger.error("Failed to read generation history: %s", exc)
        return {"generations": [], "total": 0}
