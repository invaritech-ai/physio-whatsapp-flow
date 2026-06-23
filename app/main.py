from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.middleware.request_context import RequestContextMiddleware, get_request_id
from app.scheduler import run_sync_therapist_event_types, run_sync_therapist_availability

# DEV: enable DEBUG logging for app modules to trace webhook issues
logging.basicConfig(level=logging.INFO)
logging.getLogger("app").setLevel(logging.DEBUG)

scheduler = AsyncIOScheduler()


def send_scheduled_reminders() -> None:
    """Stub for future reminder implementation."""
    pass


def _rate_limit_exception_handler(request: Request, exc: Exception) -> Response:
    """
    Adapter for SlowAPI handler with FastAPI's broader ExceptionHandler signature.
    """
    if not isinstance(exc, RateLimitExceeded):
        raise exc
    return _rate_limit_exceeded_handler(request, exc)


def _app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Centralized handler for AppException.
    Returns standardized error response with request tracing.
    """
    request_id = get_request_id() or "unknown"
    error_response = exc.to_error_response(request_id)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Keep ids stable so hot-reload/restart paths do not duplicate jobs.
    if scheduler.get_job("scheduled-reminders") is None:
        scheduler.add_job(
            send_scheduled_reminders,
            "interval",
            id="scheduled-reminders",
            minutes=5,
            replace_existing=True,
        )

    if scheduler.get_job("sync-therapist-event-types") is None:
        scheduler.add_job(
            run_sync_therapist_event_types,
            "interval",
            id="sync-therapist-event-types",
            seconds=settings.sync_interval_seconds,
            replace_existing=True,
        )

    if scheduler.get_job("sync-therapist-availability") is None:
        scheduler.add_job(
            run_sync_therapist_availability,
            "interval",
            id="sync-therapist-availability",
            seconds=settings.availability_sync_interval_seconds,
            replace_existing=True,
        )

    if not scheduler.running:
        scheduler.start()

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown()


app = FastAPI(
    title="movement-whatsapp-automation-api",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exception_handler)


# CORS configuration
def _get_cors_origins() -> list[str]:
    env = settings.app_env.strip().lower()
    if env == "development":
        return ["*"]
    if settings.web_base_url:
        return [settings.web_base_url]
    if env in {"production", "prod"}:
        raise RuntimeError(
            "WEB_BASE_URL must be configured for production CORS policy."
        )
    return ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    # Idempotency-Key is required for FE retries on payment/invoice POSTs.
    allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
    # Content-Disposition lets the FE read the server-provided (appointment-dated)
    # filename for receipt preview/PDF downloads.
    expose_headers=["X-Request-ID", "X-Response-Time-Ms", "Content-Disposition"],
)

app.add_middleware(RequestContextMiddleware)

app.add_exception_handler(AppException, _app_exception_handler)

app.include_router(api_router)
