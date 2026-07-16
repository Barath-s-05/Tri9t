"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tri9t.app.core.config import settings
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
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(ingest.router)
app.include_router(browse.router)
app.include_router(selection.router)
app.include_router(generation.router)
app.include_router(retrieval.router)
app.include_router(versions.router)
