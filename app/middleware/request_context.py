"""Request context middleware for tracing and logging."""

from __future__ import annotations

import contextvars
import logging
import time
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
request_start_time: contextvars.ContextVar[float] = contextvars.ContextVar("request_start_time", default=0.0)

_logger = logging.getLogger("app.request")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_ctx.get()


def get_request_duration_ms() -> float:
    """Get the current request duration in milliseconds."""
    start = request_start_time.get()
    if start == 0.0:
        return 0.0
    return (time.time() - start) * 1000


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds request tracing context.
    
    Features:
    - Generates or propagates X-Request-ID header
    - Tracks request duration
    - Logs request start/end with timing
    - Adds request_id to response headers
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request_id_ctx.set(request_id)
        request_start_time.set(time.time())

        method = request.method
        path = request.url.path
        query = str(request.query_params) if request.query_params else ""

        _logger.info(
            "request.started",
            extra={
                "request_id": request_id,
                "method": method,
                "path": path,
                "query": query,
            },
        )

        try:
            response = await call_next(request)
            duration_ms = get_request_duration_ms()

            _logger.info(
                "request.completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                },
            )

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time-Ms"] = f"{duration_ms:.2f}"
            return response

        except Exception as exc:
            duration_ms = get_request_duration_ms()

            _logger.exception(
                "request.failed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "duration_ms": round(duration_ms, 2),
                    "error": str(exc),
                },
            )
            raise
