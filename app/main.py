from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import AsyncIterator


from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.rate_limit import limiter
from app.middleware.request_context import RequestContextMiddleware, get_request_id

# DEV: enable DEBUG logging for app modules to trace webhook issues
logging.basicConfig(level=logging.INFO)
logging.getLogger("app").setLevel(logging.DEBUG)

scheduler = AsyncIOScheduler()


def send_scheduled_reminders() -> None:
    """
    Scheduler function for sending reminders.

    STUB: This will be reimplemented in Phase 4 (Scheduler Update).
    """
    # Phase 1: No-op to avoid crashes
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
    # Keep this id stable so hot-reload/restart paths do not duplicate jobs.
    if scheduler.get_job("scheduled-reminders") is None:
        scheduler.add_job(
            send_scheduled_reminders,
            "interval",
            id="scheduled-reminders",
            minutes=5,
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

# Static invoice document serving for generated PDF links
invoice_storage_path = Path(settings.invoice_storage_dir)
invoice_storage_path.mkdir(parents=True, exist_ok=True)
app.mount(
    "/" + settings.invoice_public_path.strip("/"),
    StaticFiles(directory=str(invoice_storage_path)),
    name="generated-invoices",
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
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    expose_headers=["X-Request-ID", "X-Response-Time-Ms"],
)

app.add_middleware(RequestContextMiddleware)

app.add_exception_handler(AppException, _app_exception_handler)

app.include_router(api_router)
