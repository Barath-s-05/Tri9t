"""Request ID middleware.

Propagates or generates an ``X-Request-ID`` header for every HTTP
request and stores it in a context variable for structured logging.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

logger = logging.getLogger(__name__)


class RequestIDMiddleware:
    """ASGI middleware that sets an X-Request-ID on every request."""

    def __init__(self, app):  # noqa: ANN001
        self.app = app

    async def __call__(self, scope, receive, send):  # noqa: ANN001, ANN204
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # Extract or generate request ID
        headers = dict(scope.get("headers", []))
        rid = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore")
        if not rid:
            rid = str(uuid.uuid4())

        request_id_var.set(rid)

        async def send_wrapper(message):  # noqa: ANN001, ANN202
            if message["type"] == "http.response.start":
                hdrs = list(message.get("headers", []))
                hdrs.append((b"x-request-id", rid.encode()))
                message["headers"] = hdrs
            await send(message)

        await self.app(scope, receive, send_wrapper)
