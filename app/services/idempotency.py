"""Idempotency service for safe request retries."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import IdempotencyKey

IDEMPOTENCY_TTL_HOURS = 24


def compute_request_hash(request_body: dict[str, Any]) -> str:
    """Compute SHA256 hash of request body for integrity verification."""
    normalized = json.dumps(request_body, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode()).hexdigest()


def get_or_create_idempotency_record(
    db: Session,
    *,
    idempotency_key: str,
    endpoint: str,
    request_body: dict[str, Any],
) -> tuple[IdempotencyKey | None, bool]:
    """
    Get existing idempotency record or create a new pending one.
    
    Returns:
        Tuple of (record, is_existing) where:
        - record: The existing or newly created record
        - is_existing: True if this is a cached response
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=IDEMPOTENCY_TTL_HOURS)

    existing = db.exec(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
    ).first()

    if existing:
        if existing.expires_at < now:
            db.delete(existing)
            db.commit()
        else:
            if existing.status == "completed":
                return existing, True
            if existing.status == "pending":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "idempotency_key_in_progress",
                        "message": "A request with this idempotency key is currently being processed",
                    },
                )

    request_hash = compute_request_hash(request_body)
    new_record = IdempotencyKey(
        idempotency_key=idempotency_key,
        endpoint=endpoint,
        request_hash=request_hash,
        response_status=0,
        response_json="",
        status="pending",
        expires_at=expires_at,
    )
    db.add(new_record)
    db.commit()
    db.refresh(new_record)

    return new_record, False


def complete_idempotency_record(
    db: Session,
    *,
    idempotency_key: str,
    response_status: int,
    response_json: str,
) -> None:
    """Mark an idempotency record as completed with the response."""
    record = db.exec(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
    ).first()

    if record:
        record.status = "completed"
        record.response_status = response_status
        record.response_json = response_json
        db.add(record)
        db.commit()


def fail_idempotency_record(
    db: Session,
    *,
    idempotency_key: str,
) -> None:
    """Mark an idempotency record as failed (allows retry with same key)."""
    record = db.exec(
        select(IdempotencyKey).where(IdempotencyKey.idempotency_key == idempotency_key)
    ).first()

    if record:
        db.delete(record)
        db.commit()


def cleanup_expired_idempotency_keys(db: Session) -> int:
    """Remove expired idempotency keys. Returns count of deleted records."""
    now = datetime.now(timezone.utc)
    expired = db.exec(
        select(IdempotencyKey).where(IdempotencyKey.expires_at < now)
    ).all()

    count = len(expired)
    for record in expired:
        db.delete(record)

    if count > 0:
        db.commit()

    return count
