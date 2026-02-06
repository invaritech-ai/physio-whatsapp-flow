from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

from app.api.router import api_router
from app.core.config import settings
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


app = FastAPI(lifespan=lifespan)

# Allow browser clients to call the API during dev.
# TODO: tighten origins for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
