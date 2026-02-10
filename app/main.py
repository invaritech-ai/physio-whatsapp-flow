from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import api_router
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.session import engine


scheduler = AsyncIOScheduler()


def send_scheduled_reminders() -> None:
    """
    Scheduler function for sending reminders.

    STUB: This will be reimplemented in Phase 4 (Scheduler Update).
    """
    # Phase 1: No-op to avoid crashes
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(send_scheduled_reminders, "interval", minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="movement-whatsapp-automation-api",
    version="0.1.0",
    lifespan=lifespan,
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
def _get_cors_origins() -> list[str]:
    if settings.app_env == "development":
        return ["*"]
    origins: list[str] = []
    if settings.web_base_url:
        origins.append(settings.web_base_url)
    return origins or ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router)
