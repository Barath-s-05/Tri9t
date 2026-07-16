"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tri9t.app.core.config import settings
from tri9t.app.middleware.timing import TimingMiddleware
from tri9t.app.core.logging import setup_logging
from tri9t.app.db.database import init_db
from tri9t.app.routers import (
    browse,
    generation,
    health,
    ingest,
    retrieval,
    selection,
    versions,
)

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Handle application startup and shutdown events."""
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    init_db()
    logger.info("Database tables created")

    # Initialise MongoDB connection
    from tri9t.app.db.mongo import close as mongo_close, ping as mongo_ping

    if mongo_ping():
        logger.info("MongoDB connected")
    else:
        logger.warning("MongoDB unreachable – generation features disabled")

    yield

    mongo_close()
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    description=(
        "Intelligent document versioning and QA test-case generation platform.\n\n"
        "**Core workflow:**\n"
        "1. **Upload** a PDF → parse into a hierarchical tree (`POST /ingest/document`)\n"
        "2. **Upload a new version** → nodes are matched across versions (`POST /versions/ingest`)\n"
        "3. **Browse & search** documents, trees, and node changes\n"
        "4. **Create selections** of specific nodes for targeted analysis\n"
        "5. **Generate QA test cases** using AI (`POST /generate`)\n"
        "6. **Track staleness** — know when generations need regeneration\n\n"
        "All UUIDs in path and query parameters are validated. "
        "Error responses follow a consistent `{error, message, hint}` structure."
    ),
    openapi_tags=[
        {"name": "health", "description": "Service health checks"},
        {"name": "ingest", "description": "PDF upload and initial parsing"},
        {"name": "browse", "description": "Document, version, and tree browsing"},
        {"name": "versions", "description": "Multi-version ingestion and change tracking"},
        {"name": "selections", "description": "Named, version-pinned node selections"},
        {"name": "generation", "description": "AI-powered QA test-case generation"},
        {"name": "retrieval", "description": "Full-text search across document nodes"},
    ],
)

app.add_middleware(TimingMiddleware)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(browse.router)
app.include_router(selection.router)
app.include_router(generation.router)
app.include_router(retrieval.router)
app.include_router(versions.router)
