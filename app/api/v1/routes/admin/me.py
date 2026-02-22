"""Admin self-service profile endpoints."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.v1.schemas.admin_me import (
    AdminPreferredTimezoneResponse,
    UpdateAdminPreferredTimezoneRequest,
    UpdateAdminPreferredTimezoneResponse,
)
from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import User

router = APIRouter(prefix="/admin", tags=["Admin - Me"])


def _normalize_and_validate_timezone(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="invalid_preferred_timezone")
    try:
        return ZoneInfo(normalized).key
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="invalid_preferred_timezone") from exc


@router.get("/me/timezone", response_model=AdminPreferredTimezoneResponse)
def get_admin_preferred_timezone(
    admin: User = Depends(get_current_admin),
):
    return AdminPreferredTimezoneResponse(preferred_timezone=admin.preferred_timezone)


@router.patch("/me/timezone", response_model=UpdateAdminPreferredTimezoneResponse)
def update_admin_preferred_timezone(
    payload: UpdateAdminPreferredTimezoneRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    admin.preferred_timezone = _normalize_and_validate_timezone(payload.preferred_timezone)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return UpdateAdminPreferredTimezoneResponse(preferred_timezone=admin.preferred_timezone)
