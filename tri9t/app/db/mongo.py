"""MongoDB client for generation storage and audit logging.

Provides a thin wrapper around pymongo for storing AI-generated
outputs and audit events.  All document data remains in SQLite;
MongoDB is used exclusively for generation artefacts.
"""

from __future__ import annotations

import logging
from typing import Any

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from tri9t.app.core.config import settings

logger = logging.getLogger(__name__)

_client: MongoClient | None = None
_db: Database | None = None


def get_client() -> MongoClient:
    """Return (and lazily create) the shared MongoClient."""
    global _client
    if _client is None:
        _client = MongoClient(
            settings.MONGO_URI,
            serverSelectionTimeoutMS=5000,
        )
    return _client


def get_db() -> Database:
    """Return the application database instance."""
    global _db
    if _db is None:
        _db = get_client()[settings.MONGO_DB_NAME]
    return _db


def get_generations_collection() -> Collection:
    """Return the ``generations`` collection."""
    return get_db()["generations"]


def get_audit_collection() -> Collection:
    """Return the ``audit_logs`` collection."""
    return get_db()["audit_logs"]


def ping() -> bool:
    """Check whether MongoDB is reachable."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False


def close() -> None:
    """Close the MongoClient and reset internal state."""
    global _client, _db
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
        _client = None
        _db = None
        logger.info("MongoDB client closed")
