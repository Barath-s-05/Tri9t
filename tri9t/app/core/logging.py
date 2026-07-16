"""Structured logging configuration."""

import logging
import logging.config
import sys
from typing import Any

from tri9t.app.core.config import settings


def setup_logging() -> dict[str, Any]:
    """Configure structured logging for the application.

    Returns:
        The logging configuration dictionary.
    """
    log_level = logging.DEBUG if settings.DEBUG else logging.INFO

    config: dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": log_level,
                "stream": sys.stdout,
            },
        },
        "root": {
            "level": log_level,
            "handlers": ["console"],
        },
        "loggers": {
            "uvicorn": {"level": "INFO"},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {"level": "INFO"},
            "sqlalchemy.engine": {"level": "WARNING"},
        },
    }

    logging.config.dictConfig(config)
    logger = logging.getLogger(__name__)
    logger.info("Logging configured at %s level", log_level)

    return config
