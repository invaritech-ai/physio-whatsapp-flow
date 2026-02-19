"""Admin endpoints for client (patient) management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from app.api.v1.schemas.client import (
    ClientCreate,
    ClientDetailResponse,
    ClientFinancialResponse,
    ClientListItem,
    ClientMessageListItem,
    ClientSessionListItem,
    ClientUpdate,
)
from app.core.auth import get_current_admin
from app.core.config import settings
from app.db.session import get_session
from app.models import Client, ClientFinancial, MessageLog, Session as TherapySession, Therapist, User

router = APIRouter(prefix="/admin/clients", tags=["Admin - Clients"])


def _ensure_client_exists(db: Session, client_id: int) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


def _ensure_preferred_therapist_exists(db: Session, therapist_id: int | None) -> None:
    if therapist_id is None:
        return
    therapist = db.get(Therapist, therapist_id)
    if not therapist:
        raise HTTPException(status_code=400, detail="Preferred therapist not found")


def _ensure_unique_phone(
    db: Session,
    phone_e164: str,
    *,
    ignore_client_id: int | None = None,
) -> None:
    existing = db.exec(select(Client).where(Client.phone_e164 == phone_e164)).first()
    if existing and existing.id != ignore_client_id:
        raise HTTPException(status_code=400, detail="Client phone already exists")


@router.get("", response_model=list[ClientListItem])
def list_clients(
    q: str | None = None,
    phone_e164: str | None = None,
    email: str | None = None,
    preferred_therapist_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List/search clients for admin workspace."""
    _ = admin
    stmt = select(Client)

    if phone_e164:
        stmt = stmt.where(Client.phone_e164 == phone_e164)
    if email:
        like_email = f"%{email.strip()}%"
        stmt = stmt.where(Client.email.ilike(like_email))  # type: ignore[arg-type]
    if preferred_therapist_id is not None:
        stmt = stmt.where(Client.preferred_therapist_id == preferred_therapist_id)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(
                Client.name.ilike(like),  # type: ignore[arg-type]
                Client.phone_e164.ilike(like),  # type: ignore[arg-type]
                Client.email.ilike(like),  # type: ignore[arg-type]
            )
        )

    stmt = stmt.order_by(Client.created_at.desc()).offset(offset).limit(limit)
    return db.exec(stmt).all()


@router.post("", response_model=ClientDetailResponse, status_code=201)
def create_client(
    data: ClientCreate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Create a new client."""
    _ = admin
    _ensure_unique_phone(db, data.phone_e164)
    _ensure_preferred_therapist_exists(db, data.preferred_therapist_id)

    client = Client(
        phone_e164=data.phone_e164,
        name=data.name,
        email=str(data.email) if data.email else None,
        date_of_birth=data.date_of_birth,
        address=data.address,
        preferred_therapist_id=data.preferred_therapist_id,
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}", response_model=ClientDetailResponse)
def get_client(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Get a single client."""
    _ = admin
    return _ensure_client_exists(db, client_id)


@router.patch("/{client_id}", response_model=ClientDetailResponse)
def update_client(
    client_id: int,
    data: ClientUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Update an existing client."""
    _ = admin
    client = _ensure_client_exists(db, client_id)

    if "phone_e164" in data.model_fields_set and data.phone_e164 is not None:
        _ensure_unique_phone(db, data.phone_e164, ignore_client_id=client.id)
        client.phone_e164 = data.phone_e164
    if "name" in data.model_fields_set:
        client.name = data.name
    if "email" in data.model_fields_set:
        client.email = str(data.email) if data.email else None
    if "date_of_birth" in data.model_fields_set:
        client.date_of_birth = data.date_of_birth
    if "address" in data.model_fields_set:
        client.address = data.address
    if "preferred_therapist_id" in data.model_fields_set:
        _ensure_preferred_therapist_exists(db, data.preferred_therapist_id)
        client.preferred_therapist_id = data.preferred_therapist_id

    client.updated_at = datetime.now(timezone.utc)
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


@router.get("/{client_id}/sessions", response_model=list[ClientSessionListItem])
def list_client_sessions(
    client_id: int,
    status: str | None = None,
    from_date: datetime | None = Query(None, alias="from"),
    to_date: datetime | None = Query(None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List sessions for a client."""
    _ = admin
    _ensure_client_exists(db, client_id)

    stmt = select(TherapySession).where(TherapySession.client_id == client_id)
    if status:
        stmt = stmt.where(TherapySession.status == status)
    if from_date:
        stmt = stmt.where(TherapySession.start_time >= from_date)
    if to_date:
        stmt = stmt.where(TherapySession.start_time <= to_date)

    stmt = stmt.order_by(TherapySession.start_time.desc()).offset(offset).limit(limit)
    return db.exec(stmt).all()


@router.get("/{client_id}/messages", response_model=list[ClientMessageListItem])
def list_client_messages(
    client_id: int,
    direction: str | None = Query(None, pattern="^(inbound|outbound)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List message history for a client."""
    _ = admin
    _ensure_client_exists(db, client_id)

    stmt = select(MessageLog).where(MessageLog.client_id == client_id)
    if direction:
        stmt = stmt.where(MessageLog.direction == direction)

    stmt = stmt.order_by(MessageLog.created_at.desc()).offset(offset).limit(limit)
    return db.exec(stmt).all()


@router.get("/{client_id}/financials", response_model=ClientFinancialResponse)
def get_client_financials(
    client_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Return current financial totals for a client."""
    _ = admin
    client = _ensure_client_exists(db, client_id)
    record = db.exec(
        select(ClientFinancial).where(ClientFinancial.client_id == client_id)
    ).first()

    if not record:
        return ClientFinancialResponse(
            client_id=client_id,
            currency=settings.default_currency,
            total_paid_cents=0,
            total_receipted_cents=0,
            available_to_receipt_cents=0,
            updated_at=client.updated_at,
        )

    available = max(record.total_paid_cents - record.total_receipted_cents, 0)
    return ClientFinancialResponse(
        client_id=client_id,
        currency=record.currency,
        total_paid_cents=record.total_paid_cents,
        total_receipted_cents=record.total_receipted_cents,
        available_to_receipt_cents=available,
        updated_at=record.updated_at,
    )
