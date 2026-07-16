"""Application-wide runtime state."""

from __future__ import annotations

import time

_startup_time: float | None = None


def record_startup() -> None:
    """Record the current time as application startup time."""
    global _startup_time
    _startup_time = time.perf_counter()


def get_uptime() -> float:
    """Return seconds elapsed since startup, or 0.0 if not started."""
    if _startup_time is None:
        return 0.0
    return time.perf_counter() - _startup_time
