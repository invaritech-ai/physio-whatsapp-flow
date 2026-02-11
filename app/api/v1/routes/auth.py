from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user, get_or_create_access_request
from app.db.session import get_session
from app.models import User


router = APIRouter()


class MeResponse(BaseModel):
    """Current user identity and access state."""

    status: str  # "approved" | "pending" | "rejected"
    role: str | None = None  # "admin" | "therapist" (only if approved)
    user_id: int | None = None
    email: str | None = None
    display_name: str | None = None
    is_active: bool | None = None


@router.get("/me", response_model=MeResponse)
def read_me(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_session),
):
    """
    Get current user's identity, role, and access state.

    Returns:
    - status: "approved" (has User record), "pending", or "rejected"
    - role/user_id/display_name: populated only when status is "approved"

    The frontend uses this to decide which view to show:
    - "approved" + role "admin" → admin dashboard
    - "approved" + role "therapist" → therapist onboarding/dashboard
    - "pending" → waiting screen
    - "rejected" → access denied screen
    - first-time visitor → auto-creates access request and returns "pending"
    """
    neon_auth_sub = current_user["user_id"]

    # Check if user exists (approved)
    user = db.exec(
        select(User).where(User.neon_auth_sub == neon_auth_sub)
    ).first()

    if user:
        return MeResponse(
            status="approved",
            role=user.role,
            user_id=user.id,
            email=user.email,
            display_name=user.display_name,
            is_active=user.is_active,
        )

    access_request = get_or_create_access_request(
        db=db,
        neon_auth_sub=neon_auth_sub,
        email=current_user.get("email"),
    )
    return MeResponse(
        status=access_request.status,
        email=access_request.email,
    )
