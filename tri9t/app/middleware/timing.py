"""Request timing middleware.

Adds an ``X-Process-Time`` header to every response and logs the
method, path, status code, and elapsed time.
"""

import logging
import time

logger = logging.getLogger(__name__)


class TimingMiddleware:
    """ASGI middleware that measures request processing time."""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.perf_counter()
        method = scope["method"]
        path = scope["path"]

        async def send_wrapper(message):  # noqa: ANN001, ANN202
            if message["type"] == "http.response.start":
                elapsed_ms = (time.perf_counter() - start) * 1000
                headers = list(message.get("headers", []))
                headers.append(
                    (b"x-process-time", f"{elapsed_ms:.2f}".encode()),
                )
                message["headers"] = headers

                status = message["status"]
                logger.info(
                    "%s %s %s %.2fms",
                    method,
                    path,
                    status,
                    elapsed_ms,
                )

            await send(message)

        await self.app(scope, receive, send_wrapper)
