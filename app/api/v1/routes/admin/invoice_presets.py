"""Admin endpoints for invoice preset management."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.v1.schemas.invoice_preset import (
    InvoicePresetCreateRequest,
    InvoicePresetItem,
    InvoicePresetUpdateRequest,
)
from app.core.auth import get_current_admin
from app.core.exceptions import BusinessLogicError, NotFoundError
from app.db.session import get_session
from app.models import InvoicePreset, User

router = APIRouter(prefix="/admin/invoice-presets", tags=["Admin - Invoice Presets"])


def _to_item(row: InvoicePreset) -> InvoicePresetItem:
    return InvoicePresetItem(
        id=row.id,
        type=row.preset_type,  # type: ignore[arg-type]
        label=row.label,
        value=row.value,
        is_active=row.is_active,
        sort_order=row.sort_order,
        updated_at=row.updated_at,
    )


def _ensure_preset_exists(db: Session, preset_id: int) -> InvoicePreset:
    row = db.get(InvoicePreset, preset_id)
    if not row:
        raise NotFoundError("invoice_preset_not_found", resource_type="invoice_preset", resource_id=preset_id)
    return row


@router.get("", response_model=list[InvoicePresetItem])
def list_invoice_presets(
    type: str | None = Query(default=None, pattern="^(diagnosis|special_note)$"),
    active: bool | None = None,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    stmt = select(InvoicePreset)
    if type is not None:
        stmt = stmt.where(InvoicePreset.preset_type == type)
    if active is not None:
        stmt = stmt.where(InvoicePreset.is_active == active)

    rows = db.exec(
        stmt.order_by(
            InvoicePreset.sort_order.asc(),
            InvoicePreset.updated_at.desc(),
            InvoicePreset.id.asc(),
        )
    ).all()
    return [_to_item(row) for row in rows]


@router.post("", response_model=InvoicePresetItem, status_code=201)
def create_invoice_preset(
    payload: InvoicePresetCreateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    now = datetime.now(timezone.utc)
    row = InvoicePreset(
        preset_type=payload.type,
        label=payload.label.strip(),
        value=payload.value.strip(),
        is_active=payload.is_active,
        sort_order=payload.sort_order,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_item(row)


@router.patch("/{preset_id}", response_model=InvoicePresetItem)
def update_invoice_preset(
    preset_id: int,
    payload: InvoicePresetUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    _ = admin
    row = _ensure_preset_exists(db, preset_id)
    if not payload.model_fields_set:
        raise BusinessLogicError("no_changes_requested")

    if "label" in payload.model_fields_set and payload.label is not None:
        row.label = payload.label.strip()
    if "value" in payload.model_fields_set and payload.value is not None:
        row.value = payload.value.strip()
    if "is_active" in payload.model_fields_set and payload.is_active is not None:
        row.is_active = payload.is_active
    if "sort_order" in payload.model_fields_set and payload.sort_order is not None:
        row.sort_order = payload.sort_order

    row.updated_at = datetime.now(timezone.utc)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_item(row)
