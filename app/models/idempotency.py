"""Idempotency key model for safe request retries."""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial

from sqlmodel import Field, SQLModel


class IdempotencyKey(SQLModel, table=True):
    """
    Stores idempotency keys to prevent duplicate operations.
    
    When a client sends a request with an Idempotency-Key header,
    the response is cached for 24 hours. Subsequent requests with
    the same key return the cached response.
    """

    __tablename__ = "idempotency_key"  # type: ignore

    id: int | None = Field(default=None, primary_key=True)
    idempotency_key: str = Field(unique=True, index=True, max_length=128)
    endpoint: str = Field(max_length=255, index=True)
    request_hash: str = Field(max_length=64)
    response_status: int
    response_json: str
    status: str = Field(default="pending", max_length=20, index=True)
    created_at: datetime = Field(default_factory=partial(datetime.now, timezone.utc), index=True)
    expires_at: datetime = Field(index=True)
