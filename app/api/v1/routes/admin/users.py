"""Admin endpoints for user management (role changes)."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import Therapist, User
from app.api.v1.schemas.user import (
    UpdateRoleRequest,
    UpdateRoleResponse,
    UserListResponse,
)

router = APIRouter(prefix="/admin/users", tags=["Admin - Users"])


@router.get("", response_model=list[UserListResponse])
def list_users(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List all approved users with their current roles."""
    users = db.exec(select(User).order_by(User.created_at.desc())).all()

    result = []
    for user in users:
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == user.id)
        ).first()
        result.append(
            UserListResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
                is_active=user.is_active,
                has_therapist_profile=therapist is not None,
                created_at=user.created_at,
            )
        )

    return result


@router.patch("/{user_id}/role", response_model=UpdateRoleResponse)
def update_user_role(
    user_id: int,
    data: UpdateRoleRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    Change a user's role between 'admin' and 'therapist'.

    Transactional rules:
    - Cannot demote the last active admin
    - admin → therapist: creates Therapist profile if none exists, reactivates if inactive
    - therapist → admin: retains Therapist profile (deactivated)
    """
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_role = target_user.role

    if previous_role == data.role:
        raise HTTPException(
            status_code=400,
            detail=f"User already has role '{data.role}'",
        )

    # Prevent demoting the last active admin
    if previous_role == "admin" and data.role == "therapist":
        active_admin_count = db.exec(
            select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active == True,  # noqa: E712
            )
        ).one()
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last active admin",
            )

    therapist_id = None

    if data.role == "therapist":
        # admin → therapist: ensure Therapist profile exists
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == target_user.id)
        ).first()

        if therapist:
            # Reactivate existing profile
            therapist.is_active = True
            therapist.display_name = target_user.display_name
            db.add(therapist)
        else:
            # Create new Therapist profile
            therapist = Therapist(
                user_id=target_user.id,
                display_name=target_user.display_name,
                is_active=False,  # Needs onboarding before activation
            )
            db.add(therapist)
            db.flush()

        therapist_id = therapist.id

    elif data.role == "admin":
        # therapist → admin: deactivate Therapist profile (retain data)
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == target_user.id)
        ).first()
        if therapist:
            therapist.is_active = False
            db.add(therapist)

    # Update the user's role
    target_user.role = data.role
    target_user.updated_at = datetime.now(timezone.utc)
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    return UpdateRoleResponse(
        user_id=target_user.id,
        email=target_user.email,
        previous_role=previous_role,
        new_role=target_user.role,
        therapist_id=therapist_id,
        message=f"Role changed from '{previous_role}' to '{data.role}'",
    )
